# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fetch the Slack messages this user received, into the store.

Run by `select_intake.py` before every scheduled intake tick. It reads
whichever conversations the user belongs to, advances a per-conversation
watermark, and writes rows through the same normalizer the fixtures use — so
a live message and a fixture message become the same shape of row.

What it needs is a **user** token. A bot token cannot read a person's direct
messages: it sees only the conversations the bot itself was added to. That
distinction is the single most common way this setup goes wrong, so the token
is classified before anything else happens and a bot token is named as such
rather than left to fail later with an empty result.

The token normally arrives as an OpenShell placeholder rather than a secret.
The gateway holds the credential and the egress proxy substitutes it on the
way to Slack, so this process handles an opaque string it cannot spend. A
literal `xoxp-` in the environment works too, for a Hermes install with no
OpenShell in front of it.

Exit codes carry the diagnosis, because the text cannot: a failing collector's
output is deliberately dropped by the selector rather than written to a job
log (see `select_intake.collect`). The code is what survives.

    0  fetched, possibly nothing new — or never configured, which is a
       state rather than a fault, and must not cost a scheduled wake
    1  something else went wrong
    2  configured before and the credential has gone, or is the wrong type,
       or was rejected, or slack.com could not be reached
    3  Slack asked us to slow down
    4  the token works but lacks a scope this recipe cannot do without
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from _db import ensure_store, ledger_path, write_txn
from normalize import insert_items, slack_message_to_item

API = "https://slack.com/api/"

EXIT_OK = 0
EXIT_OTHER = 1
EXIT_CREDENTIAL = 2
EXIT_RATE_LIMIT = 3
EXIT_SCOPE = 4

# Conversation families this recipe reads. Private channels are deliberately
# absent: `groups:*` commonly needs workspace-admin approval, and a manifest
# that asks for a scope the admin refuses can cost the user the whole install.
# The README says so, and adding them later is a manifest change plus one entry
# here.
FAMILIES = {
    "im": "im:history",
    "mpim": "mpim:history",
    "public_channel": "channels:history",
}

PAGE = 200  # Slack's maximum for conversations.history.

# How far back the first run reaches, per conversation.
#
# The alternative — no lower bound, page until Slack stops — drains a channel's
# entire history in one tick. On an account in a dozen channels with years of
# backlog that is tens of thousands of requests, which rate-limits, which
# throws away the run, which starts again from the top on the next tick. The
# first run would never finish.
#
# A window is a better bound than a page cap, because it keeps every crawl
# *complete*: paging always reaches the end of the window, so the watermark can
# be advanced safely. A page cap would leave a gap above the watermark that
# nothing would ever come back for.
BACKFILL_DAYS = 7

# How many Slack calls one tick may spend.
#
# Slack documents one request per minute and fifteen messages per response for
# `conversations.history` on affected non-Marketplace apps. That is restrictive
# enough to shape the design rather than be absorbed by retries: a workspace
# sweep cannot finish, and a tick that tries will spend its whole window being
# throttled and then discard the work. So coverage is bounded and rotates —
# each tick serves the conversations the last one did not reach, and says so
# when it ran out of budget rather than reporting an empty result.
REQUEST_BUDGET = 10
MAX_BACKOFF_SECONDS = 30

# Public channels are read only when the operator names them. Direct messages
# and group DMs need no list: they are the user's by definition, and they are
# the reason this recipe wants a user token at all.
SCOPE_FILE = "slack_channels.json"

# Message subtypes worth judging. Everything else — joins, leaves, topic
# changes, pinned notices — is Slack talking about the channel rather than a
# person talking to the user, and in a DM it would arrive as `direct`, this
# recipe's highest-priority class.
KEPT_SUBTYPES = {None, "thread_broadcast", "file_share"}


class Budget:
    """How many calls are left, and whether anything was left unread.

    Passing this around rather than counting globally keeps the accounting
    honest across the probe, the listing and the per-conversation crawl — all
    three spend from the same allowance, because Slack counts them the same
    way.
    """

    def __init__(self, allowance: int) -> None:
        self.left = allowance
        self.exhausted = False

    def spend(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return False
        self.left -= 1
        return True


class SlackError(Exception):
    """A Slack API call that came back `ok: false`."""

    def __init__(self, method: str, error: str) -> None:
        super().__init__(f"{method}: {error}")
        self.method = method
        self.error = error


def classify_token(raw: str | None) -> str:
    """Name what kind of credential this is before spending a call on it.

    Slack's token prefixes are load-bearing here.

    `xoxe.xoxp-` is what this recipe wants: a rotating user token, refreshed by
    the gateway. `xoxp-` is the non-rotating kind, which never expires — a
    permanent key to one person's whole Slack, and refused for that reason
    rather than because it would not work. `xoxb-` is a bot token, which cannot
    see a person's direct messages at all.

    A bot token fails in the way that matters most: not with an error, but with
    an empty result that looks like a quiet week. Naming the prefix costs one
    comparison and turns a silent wrong answer into a sentence saying which
    token to use instead.
    """
    token = (raw or "").strip()
    if not token:
        return "absent"
    if token.startswith("openshell:resolve:"):
        return "placeholder"
    if token.startswith("xoxe.xoxp-"):
        return "rotating"
    if token.startswith("xoxp-"):
        return "static"
    if token.startswith("xoxb-"):
        return "bot"
    if token.startswith("xapp-"):
        return "app"
    return "unrecognised"


def _explain(kind: str) -> str:
    if kind == "absent":
        return ("SLACK_USER_TOKEN is not set. Run scripts/setup-slack.sh, or "
                "see docs/set-up-slack.md.")
    if kind == "bot":
        return ("SLACK_USER_TOKEN holds a bot token (xoxb-). A bot cannot read "
                "your direct messages. Copy the User OAuth Token instead — it "
                "starts with xoxp- and sits above the bot token on the same "
                "OAuth & Permissions page.")
    if kind == "app":
        return ("SLACK_USER_TOKEN holds an app-level token (xapp-). That one is "
                "for Socket Mode. This recipe needs the User OAuth Token "
                "(xoxp-).")
    if kind == "static":
        return ("SLACK_USER_TOKEN holds a non-rotating user token (xoxp-). "
                "This recipe requires a rotating one: a token that never "
                "expires is a permanent key to your whole Slack, and the "
                "gateway is what keeps it short-lived. Create the app from "
                "docs/slack_app_manifest.json, which enables token rotation, "
                "and run scripts/setup-slack.sh.")
    return ("SLACK_USER_TOKEN does not look like a Slack token. Expected a "
            "User OAuth Token starting with xoxp-.")


def call(method: str, token: str, **params: Any) -> dict[str, Any]:
    """One Slack API call. Raises `SlackError` on `ok: false`.

    The token goes in the header and never into a log line, an exception
    message, or the returned payload. On the OpenShell path it is a placeholder
    anyway, but this collector must be equally safe on a plain Hermes install
    where it is the real thing.
    """
    query = {k: v for k, v in params.items() if v is not None}
    url = API + method + ("?" + urllib.parse.urlencode(query) if query else "")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            # Slack says how long to wait. Honour it when the wait is short
            # enough to be worth holding the tick for, and give up otherwise
            # rather than sleeping through the next scheduled run.
            wait = exc.headers.get("Retry-After") if exc.headers else None
            try:
                seconds = int(wait) if wait else 0
            except ValueError:
                seconds = 0
            if 0 < seconds <= MAX_BACKOFF_SECONDS:
                time.sleep(seconds)
                raise SlackError(method, "retry_after") from None
            raise SlackError(method, "ratelimited") from None
        # The body can quote the request, so it is not repeated here.
        raise SlackError(method, f"http_{exc.code}") from None
    except urllib.error.URLError:
        # Reaching Slack at all is the egress proxy's business; a blocked host
        # looks like this and is worth distinguishing from a bad token.
        raise SlackError(method, "unreachable") from None
    if not payload.get("ok"):
        raise SlackError(method, str(payload.get("error") or "unknown"))
    return payload


def bounded_budget() -> int:
    """Read `INTAKE_SLACK_BUDGET`, bounded, the way the selectors read theirs.

    Unvalidated, a zero or a negative would mean "spend nothing" and every tick
    would report total incomplete coverage while looking like a working run.
    """
    raw = os.environ.get("INTAKE_SLACK_BUDGET")
    if raw is None or raw == "":
        return REQUEST_BUDGET
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(
            f"INTAKE_SLACK_BUDGET must be a whole number between 1 and 200; "
            f"got {raw!r}")
    if value < 1 or value > 200:
        raise SystemExit(
            f"INTAKE_SLACK_BUDGET must be between 1 and 200; got {value}")
    return value


def capabilities_path():
    return ledger_path().parent.parent / "slack_capabilities.json"


def probe(token: str) -> dict[str, Any]:
    """Ask the workspace what this token can actually do.

    Granted scopes are not a property of the manifest — an admin can approve an
    app with less than it asked for, and organisations differ in what they
    allow at all.

    Each family is probed with the call the collector will really make. Probing
    `users.conversations` alone was wrong: it needs `im:read`, and an install
    that granted `im:read` while withholding `im:history` — the plausible
    split, since history is the sensitive half — passed the probe and then
    failed on the first fetch. That produced exit 4 on every tick, waking the
    model every half hour, and `--recheck` could not clear it because the probe
    itself was the thing that was wrong.

    `im` is the floor. A recipe that cannot read the user's direct messages is
    not doing the job it claims to, so that one is fatal; the rest degrade to
    "skipped" and are reported.
    """
    identity = call("auth.test", token)  # one call, outside the tick budget
    available: list[str] = []
    missing: list[str] = []
    for family in FAMILIES:
        if family == "public_channel":
            # Not enumerated, for the same reason it is not collected by
            # enumeration: at one request per minute a workspace sweep is not
            # affordable, and an unnamed channel is not read anyway. Probe the
            # first channel the operator named, or skip the family entirely.
            named = named_channels()
            if not named:
                continue
            channels = [{"id": named[0]}]
        else:
            try:
                listing = call("users.conversations", token, types=family,
                               limit=1)
            except SlackError as exc:
                if exc.error in ("missing_scope", "not_allowed_token_type"):
                    missing.append(family)
                    continue
                raise
            channels = listing.get("channels") or []
        if not channels:
            # Nothing to read in this family, so history access cannot be
            # tested and does not matter. Treat it as available rather than
            # inventing a failure out of an empty account.
            available.append(family)
            continue
        try:
            call("conversations.history", token,
                 channel=channels[0]["id"], limit=1)
        except SlackError as exc:
            if exc.error in ("missing_scope", "not_allowed_token_type"):
                missing.append(family)
                continue
            raise
        available.append(family)
    return {
        "user_id": identity.get("user_id"),
        "team_id": identity.get("team_id"),
        "credential": fingerprint(token),
        "available": available,
        "missing": missing,
    }


def fingerprint(token: str) -> str:
    """Identify a credential without storing it.

    The cache holds a `user_id` that the collector compares every message
    against. If the token is replaced with one belonging to somebody else and
    the cache is not invalidated, that comparison is made against the previous
    owner — and the new owner's own outgoing messages are ingested as messages
    they received.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def load_capabilities(token: str, *, refresh: bool = False) -> dict[str, Any]:
    path = capabilities_path()
    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("user_id") and cached.get("credential") == fingerprint(token):
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    caps = probe(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(caps, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return caps


def scope_path():
    return ledger_path().parent.parent / SCOPE_FILE


def named_channels() -> list[str]:
    """The public channels the operator asked for, if any.

    A workspace sweep is not an option at one request per minute, and it is not
    wanted either — a recipe that reads every channel a person happens to be in
    collects far more than the job needs. Direct messages need no such list.
    """
    path = scope_path()
    if not path.exists():
        return []
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(declared, dict):
        declared = declared.get("channels") or []
    return [str(c) for c in declared if str(c).strip()]


def conversations(token: str, families: list[str],
                  budget: Budget) -> list[dict[str, Any]]:
    """The conversations this tick will consider.

    Direct and group messages are enumerated, because they are the user's by
    definition and there is no list to keep. Public channels are taken from
    `slack_channels.json` — naming them is what makes coverage bounded, and
    unnamed channels are simply not read.
    """
    found: list[dict[str, Any]] = []
    for family in families:
        if family == "public_channel":
            found.extend({"id": cid, "type": "channel"}
                         for cid in named_channels())
            continue
        cursor = None
        while True:
            if not budget.spend():
                return found
            page = call("users.conversations", token, types=family,
                        exclude_archived="true", limit=PAGE, cursor=cursor)
            for channel in page.get("channels", []):
                found.append({"id": channel["id"],
                              "type": family_of(channel, family)})
            cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
    return found


def family_of(channel: dict[str, Any], requested: str) -> str:
    """Map Slack's flags onto the four types the normalizer understands."""
    if channel.get("is_im"):
        return "im"
    if channel.get("is_mpim"):
        return "mpim"
    if channel.get("is_private"):
        return "group"
    return "channel" if requested == "public_channel" else requested


def history(token: str, channel_id: str, oldest: str | None,
            budget: Budget) -> tuple[list[dict[str, Any]], bool]:
    """Messages since the watermark, oldest first, and whether the crawl finished.

    Completeness is returned rather than assumed, because the watermark depends
    on it. `conversations.history` pages from newest backwards, so a crawl that
    stops early holds the *newest* messages and is missing older ones — and the
    gap sits above the watermark, where `oldest=` will never look again.
    Advancing the cursor after an incomplete crawl loses those messages
    permanently, silently, on a run that exits zero.

    Under a `BACKFILL_DAYS` window this should not happen: paging always
    reaches the end of the window. `has_more` with no cursor to follow is the
    case that would, so it is reported rather than smoothed over.
    """
    if oldest is None:
        oldest = f"{time.time() - BACKFILL_DAYS * 86400:.6f}"
    messages: list[dict[str, Any]] = []
    cursor = None
    complete = True
    while True:
        if not budget.spend():
            complete = False
            break
        page = call("conversations.history", token, channel=channel_id,
                    oldest=oldest, inclusive="false", limit=PAGE, cursor=cursor)
        messages.extend(page.get("messages", []))
        if not page.get("has_more"):
            break
        cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            complete = False
            break
    messages.sort(key=lambda m: float(m.get("ts", "0")))
    return messages, complete


def replies(token: str, channel_id: str, parent_ts: str, oldest: str | None,
            budget: Budget) -> tuple[list[dict[str, Any]], bool]:
    """The replies under one thread parent.

    `conversations.history` returns thread parents and broadcast replies, not
    ordinary replies — those live behind `conversations.replies`. Without this,
    a colleague answering inside a thread in the user's own DM never becomes an
    item, never becomes an obligation, and never appears in the shortlist. The
    recipe's central promise fails with no error and no log line.

    Paginated, and it reports whether it finished. A thread with more replies
    than one page holds would otherwise lose the remainder the moment the
    channel watermark moved past the parent — the same silent gap the channel
    crawl has, one level down. An unfinished thread holds the channel's
    watermark back, so the next tick reads the window again.

    Returns the replies and whether the crawl completed.
    """
    gathered: list[dict[str, Any]] = []
    cursor = None
    complete = True
    while True:
        if not budget.spend():
            complete = False
            break
        page = call("conversations.replies", token, channel=channel_id,
                    ts=parent_ts, oldest=oldest, inclusive="false",
                    limit=PAGE, cursor=cursor)
        # The parent comes back with its replies; it is already accounted for.
        gathered.extend(m for m in page.get("messages", [])
                        if m.get("ts") != parent_ts)
        if not page.get("has_more"):
            break
        cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            complete = False
            break
    return gathered, complete


def worth_judging(message: dict[str, Any], user_id: str | None) -> bool:
    """Is this a person saying something to the user?

    A message the user sent is not one they received. Neither is Slack
    announcing that somebody joined, and neither is a CI app posting a build
    result — both of which arrive in a DM as `direct`, the highest-priority
    class this recipe has, and the second with no `user` field at all, so the
    sender lands NULL.
    """
    if message.get("subtype") not in KEPT_SUBTYPES:
        return False
    if message.get("bot_id"):
        return False
    return message.get("user") != user_id


def sender_name(token: str, user_id: str | None, cache: dict[str, str | None],
                budget: Budget) -> str | None:
    """Resolve one display name, or give up quietly.

    Slack's own guidance for a large workspace, learned the expensive way on
    one: never enumerate the member list. Names are resolved one at a time and
    cached for the run. A raw `U0…` id is useless to a reader, but failing the
    whole collection because one lookup was rate-limited would be worse.
    """
    if not user_id:
        return None
    if user_id not in cache:
        if not budget.spend():
            # A name is cosmetic; the message is not. Do not spend the last
            # call on decoration, and do not cache the miss — a later tick
            # with budget left should still be able to resolve it.
            return None
        try:
            profile = call("users.info", token, user=user_id).get("user", {})
            cache[user_id] = (profile.get("profile", {}).get("display_name")
                              or profile.get("real_name") or None)
        except SlackError:
            cache[user_id] = None
    return cache[user_id]


def read_cursors() -> dict[str, str]:
    with write_txn() as conn:
        return {row[0]: row[1] for row in conn.execute(
            "SELECT scope, cursor FROM cursors WHERE source='slack'")}


def commit_channel(channel: dict[str, Any], items: list[dict[str, Any]],
                   watermark: str | None) -> int:
    """Rows and their watermark, together or not at all.

    One short transaction per conversation. The fetch happens outside it: a
    connection held open across a network call is a write lock held for the
    length of that call, which `_db.py` says in as many words, and on a first
    run that would be minutes during which the user's own corrections cannot
    be written.
    """
    with write_txn() as conn:
        added = insert_items(conn, items) if items else 0
        if watermark is not None:
            conn.execute(
                "INSERT INTO cursors(source, scope, cursor) VALUES ('slack',?,?)"
                " ON CONFLICT(source, scope) DO UPDATE SET cursor=excluded.cursor,"
                " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (channel["id"], watermark))
    return added


def threads_path():
    return scope_path().with_name("slack_threads.json")


def read_threads(channel_id: str) -> dict[str, str | None]:
    """Per-thread watermarks for one conversation.

    Collection bookkeeping rather than anything the agent judges, kept beside
    the store and rebuilt harmlessly if lost — every thread is simply re-read
    from the channel's own window once.
    """
    try:
        stored = json.loads(threads_path().read_text(encoding="utf-8"))
        return dict(stored.get(channel_id, {}))
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def save_threads(channel_id: str, threads: dict[str, str | None]) -> None:
    path = threads_path()
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except (OSError, json.JSONDecodeError):
        existing = {}
    existing[channel_id] = threads
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing), encoding="utf-8")
    except OSError:
        # Losing this costs a re-read, not correctness.
        pass


def rotation_offset(count: int) -> int:
    """Where this tick starts in the conversation list.

    A bounded tick that always starts at the same place would serve the first
    few conversations forever and never reach the rest. The offset advances by
    however many were served, so coverage rotates and every conversation is
    reached within a few ticks rather than never.
    """
    path = scope_path().with_name("slack_rotation.json")
    try:
        offset = int(json.loads(path.read_text(encoding="utf-8"))["offset"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        offset = 0
    return offset % count if count else 0


def save_rotation(offset: int) -> None:
    path = scope_path().with_name("slack_rotation.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    except OSError:
        # Losing the offset costs coverage fairness, not correctness.
        pass


def collect(token: str, caps: dict[str, Any],
            budget: Budget) -> tuple[dict[str, Any], bool]:
    """Fetch what the budget allows, starting where the last tick stopped.

    A failure in one conversation used to abort the run and roll back every
    conversation already fetched — so a single rate-limited channel meant zero
    rows stored and zero progress, and the next tick reproduced it exactly.
    Progress has to be monotonic under partial failure, or the schedule is a
    livelock that wakes the model every half hour to redo work it will discard.
    """
    ensure_store()
    channels = conversations(token, caps["available"], budget)
    watermarks = read_cursors()
    names: dict[str, str | None] = {}
    fetched = added = served = failed_conversations = 0
    partial: list[dict[str, str]] = []
    incomplete: list[str] = []

    start = rotation_offset(len(channels))
    ordered = channels[start:] + channels[:start]

    for channel in ordered:
        if budget.left <= 0:
            budget.exhausted = True
            break
        served += 1
        try:
            messages, complete = history(token, channel["id"],
                                         watermarks.get(channel["id"]), budget)
        except SlackError as exc:
            # The conversation id is not repeated: a DM id names who the user
            # talks to, and this summary is the agent's prompt.
            failed_conversations += 1
            partial.append({"family": channel["type"], "error": exc.error})
            continue
        # No early exit on an empty channel. A quiet conversation is exactly
        # where a thread reply hides: the parent is already below the
        # watermark, so `conversations.history` returns nothing, and skipping
        # here would mean the thread is never revisited at all.
        #
        # A thread parent whose reply count moved since the watermark has
        # replies this tick has not seen — but a parent's `ts` never changes,
        # so once the channel watermark passes it the parent is never returned
        # again, and a reply arriving after that would be invisible for as long
        # as the thread stayed alive. Threads therefore carry their own
        # watermark: remembered when first seen, re-read on later ticks from
        # wherever their own reading stopped.
        known = read_threads(channel["id"])
        for message in messages:
            if message.get("reply_count"):
                known.setdefault(message["ts"], None)

        threaded: list[dict[str, Any]] = []
        threads_complete = True
        for parent_ts in sorted(known):
            if budget.left <= 0:
                threads_complete = False
                break
            try:
                found, done = replies(token, channel["id"], parent_ts,
                                      known[parent_ts], budget)
            except SlackError as exc:
                # A thread that could not be read is not a conversation that
                # could not be read: the parents are already in hand and worth
                # storing. Reported, but it does not make the run a failure.
                partial.append({"family": channel["type"], "scope": "thread",
                                "error": exc.error})
                threads_complete = False
                break
            threaded.extend(found)
            if done and found:
                known[parent_ts] = found[-1]["ts"]
            elif not done:
                threads_complete = False
        save_threads(channel["id"], known)

        items = [
            slack_message_to_item(message, channel, caps["user_id"],
                                  sender_name(token, message.get("user"), names, budget))
            for message in messages + threaded
            if worth_judging(message, caps["user_id"])
        ]
        if not items:
            continue
        fetched += len(items)
        # Only a complete crawl may move the watermark; the rows are idempotent
        # on `source_id`, so re-reading an unmoved window costs nothing.
        # An unfinished thread crawl holds the channel back too: advancing
        # past a parent whose replies were truncated is how those replies would
        # be lost for good.
        watermark = (messages[-1]["ts"]
                     if (messages and complete and threads_complete) else None)
        if not complete or not threads_complete:
            incomplete.append(channel["type"])
        added += commit_channel(channel, items, watermark)

    if channels:
        save_rotation((start + served) % len(channels))

    result: dict[str, Any] = {
        "conversations": len(channels),
        "served": served,
        "fetched": fetched,
        "added": added,
        "skipped_families": caps["missing"],
    }
    if partial:
        result["partial"] = partial
    if incomplete or budget.exhausted or served < len(channels):
        # Coverage that was not achieved is reported rather than being left to
        # look like an absence of messages.
        result["incomplete_coverage"] = {
            "budget_exhausted": budget.exhausted,
            "conversations_unserved": max(0, len(channels) - served),
            "truncated_families": sorted(set(incomplete)),
        }
    # A run that reached nothing is a failed run. One where some conversations
    # worked made progress and must not throw it away — and a thread failing
    # inside a conversation that otherwise succeeded is neither.
    total_failed = served > 0 and failed_conversations == served
    return result, total_failed


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    refresh = "--recheck" in args

    raw = os.environ.get("SLACK_USER_TOKEN")
    kind = classify_token(raw)

    # Never configured is not the same as broken, and the difference decides
    # whether every idle tick wakes the model.
    #
    # This file existing is what makes the selector run it, and most people
    # will have it long before they connect Slack. If an absent token counted
    # as a failure, the gate that keeps an empty tick free would never fire
    # again — the model would be woken every half hour, forever, to be told
    # there is nothing to do.
    #
    # The hole in that reasoning is a credential that *disappears*: a detached
    # provider empties the variable, which then looks like "never set up". The
    # capability cache closes it. It is written on the first successful run, so
    # its presence means Slack was connected once, and a missing token after
    # that is a failure rather than a state.
    if kind == "absent":
        if capabilities_path().exists():
            print("Slack was connected and SLACK_USER_TOKEN has gone. If this "
                  "sandbox uses an OpenShell provider, check it is still "
                  "attached: openshell sandbox provider list <sandbox>.",
                  file=sys.stderr)
            return EXIT_CREDENTIAL
        print(json.dumps({"unconfigured": True}))
        return EXIT_OK

    if kind not in ("placeholder", "rotating"):
        print(_explain(kind), file=sys.stderr)
        return EXIT_CREDENTIAL

    token = (raw or "").strip()
    try:
        caps = load_capabilities(token, refresh=refresh)
    except SlackError as exc:
        return _report_failure(exc)

    if "im" not in caps["available"]:
        print("The token works but cannot read direct messages. Add "
              "`im:read` and `im:history` to the app's User Token Scopes, "
              "reinstall it, then re-run with --recheck.", file=sys.stderr)
        return EXIT_SCOPE

    budget = Budget(bounded_budget())
    try:
        result, everything_failed = collect(token, caps, budget)
    except SlackError as exc:
        return _report_failure(exc)

    print(json.dumps(result))
    if everything_failed:
        errors = sorted({entry["error"] for entry in result["partial"]})
        print(f"Every conversation failed ({', '.join(errors)}).",
              file=sys.stderr)
        throttled = {"ratelimited", "retry_after"}
        return (EXIT_RATE_LIMIT if set(errors) <= throttled else EXIT_OTHER)
    return EXIT_OK


def _report_failure(exc: SlackError) -> int:
    """Map a Slack error onto an exit code, saying only what is safe to say."""
    credential = {"invalid_auth", "not_authed", "token_revoked",
                  "account_inactive", "token_expired"}
    if exc.error in credential:
        print(f"Slack rejected the credential ({exc.error}). See "
              "docs/set-up-slack.md.", file=sys.stderr)
        return EXIT_CREDENTIAL
    if exc.error in ("ratelimited", "retry_after"):
        print("Slack asked us to slow down; the next tick will resume from the "
              "same watermark.", file=sys.stderr)
        return EXIT_RATE_LIMIT
    if exc.error == "missing_scope":
        print("The app is missing a scope this call needs. Re-run with "
              "--recheck after reinstalling it.", file=sys.stderr)
        return EXIT_SCOPE
    if exc.error == "unreachable":
        print("Could not reach slack.com. If this sandbox has an egress "
              "policy, it needs to allow slack.com — and the provider must be "
              "attached to this sandbox for the credential to be substituted.",
              file=sys.stderr)
        return EXIT_CREDENTIAL
    print(f"Slack call failed ({exc.method}: {exc.error}).", file=sys.stderr)
    return EXIT_OTHER


if __name__ == "__main__":
    raise SystemExit(main())
