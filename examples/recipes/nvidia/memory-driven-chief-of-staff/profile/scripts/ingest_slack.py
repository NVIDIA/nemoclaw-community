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

# Message subtypes worth judging. Everything else — joins, leaves, topic
# changes, pinned notices — is Slack talking about the channel rather than a
# person talking to the user, and in a DM it would arrive as `direct`, this
# recipe's highest-priority class.
KEPT_SUBTYPES = {None, "thread_broadcast", "file_share"}


class SlackError(Exception):
    """A Slack API call that came back `ok: false`."""

    def __init__(self, method: str, error: str) -> None:
        super().__init__(f"{method}: {error}")
        self.method = method
        self.error = error


def classify_token(raw: str | None) -> str:
    """Name what kind of credential this is before spending a call on it.

    Slack's token prefixes are load-bearing here. `xoxb-` is a bot token, which
    silently cannot see direct messages; `xoxe.xoxp-` is a rotating user token,
    whose access half expires in hours and which this recipe does not refresh.
    Both fail in ways that look like "no new messages" rather than like an
    error, which is why they are rejected up front.
    """
    token = (raw or "").strip()
    if not token:
        return "absent"
    if token.startswith("openshell:resolve:"):
        return "placeholder"
    if token.startswith("xoxe.xoxp-"):
        return "rotating"
    if token.startswith("xoxp-"):
        return "user"
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
    if kind == "rotating":
        return ("SLACK_USER_TOKEN holds a rotating user token (xoxe.xoxp-). "
                "This recipe supports static user tokens only; its access half "
                "would expire within hours and nothing here refreshes it. "
                "Create the app from docs/slack_app_manifest.json, which sets "
                "token_rotation_enabled to false.")
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
    identity = call("auth.test", token)
    available: list[str] = []
    missing: list[str] = []
    for family in FAMILIES:
        try:
            listing = call("users.conversations", token, types=family, limit=1)
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


def conversations(token: str, families: list[str]) -> list[dict[str, Any]]:
    """Every conversation the user belongs to, in the families they granted.

    `users.conversations` rather than `conversations.list`: the second returns
    the whole workspace, which on a large one is both a rate limit and a
    privacy surprise. This recipe only wants what the user is already in.
    """
    found: list[dict[str, Any]] = []
    for family in families:
        cursor = None
        while True:
            page = call("users.conversations", token, types=family,
                        exclude_archived="true", limit=PAGE, cursor=cursor)
            for channel in page.get("channels", []):
                found.append({"id": channel["id"], "type": family_of(channel, family)})
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


def history(token: str, channel_id: str,
            oldest: str | None) -> tuple[list[dict[str, Any]], bool]:
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


def sender_name(token: str, user_id: str | None, cache: dict[str, str | None]) -> str | None:
    """Resolve one display name, or give up quietly.

    Slack's own guidance for a large workspace, learned the expensive way on
    one: never enumerate the member list. Names are resolved one at a time and
    cached for the run. A raw `U0…` id is useless to a reader, but failing the
    whole collection because one lookup was rate-limited would be worse.
    """
    if not user_id:
        return None
    if user_id not in cache:
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


def collect(token: str, caps: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Fetch every granted family, one conversation at a time.

    A failure in one conversation used to abort the run and roll back every
    conversation already fetched — so a single rate-limited channel meant zero
    rows stored and zero progress, and the next tick reproduced it exactly.
    Progress has to be monotonic under partial failure, or the schedule is a
    livelock that wakes the model every half hour to redo work it will discard.
    """
    ensure_store()
    channels = conversations(token, caps["available"])
    watermarks = read_cursors()
    names: dict[str, str | None] = {}
    fetched = added = 0
    partial: list[dict[str, str]] = []
    incomplete: list[str] = []

    for channel in channels:
        try:
            messages, complete = history(token, channel["id"],
                                         watermarks.get(channel["id"]))
        except SlackError as exc:
            # The conversation id is not repeated: a DM id names who the user
            # talks to, and this summary is the agent's prompt.
            partial.append({"family": channel["type"], "error": exc.error})
            continue
        if not messages:
            continue
        items = [
            slack_message_to_item(message, channel, caps["user_id"],
                                  sender_name(token, message.get("user"), names))
            for message in messages
            if worth_judging(message, caps["user_id"])
        ]
        fetched += len(items)
        # Only a complete crawl may move the watermark; the rows are idempotent
        # on `source_id`, so re-reading an unmoved window costs nothing.
        watermark = messages[-1]["ts"] if complete else None
        if not complete:
            incomplete.append(channel["type"])
        added += commit_channel(channel, items, watermark)

    result: dict[str, Any] = {
        "conversations": len(channels),
        "fetched": fetched,
        "added": added,
        "skipped_families": caps["missing"],
    }
    if partial:
        result["partial"] = partial
    if incomplete:
        result["incomplete"] = incomplete
    # A run in which every conversation failed is a failed run; one in which
    # some succeeded made progress and must not throw it away.
    total_failed = bool(partial) and len(partial) == len(channels)
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

    if kind not in ("placeholder", "user"):
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

    try:
        result, everything_failed = collect(token, caps)
    except SlackError as exc:
        return _report_failure(exc)

    print(json.dumps(result))
    if everything_failed:
        errors = sorted({entry["error"] for entry in result["partial"]})
        print(f"Every conversation failed ({', '.join(errors)}).",
              file=sys.stderr)
        return (EXIT_RATE_LIMIT if errors == ["ratelimited"] else EXIT_OTHER)
    return EXIT_OK


def _report_failure(exc: SlackError) -> int:
    """Map a Slack error onto an exit code, saying only what is safe to say."""
    credential = {"invalid_auth", "not_authed", "token_revoked",
                  "account_inactive", "token_expired"}
    if exc.error in credential:
        print(f"Slack rejected the credential ({exc.error}). See "
              "docs/set-up-slack.md.", file=sys.stderr)
        return EXIT_CREDENTIAL
    if exc.error == "ratelimited":
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
