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

    0  fetched (possibly nothing new)
    1  something else went wrong
    2  credential problem — absent, wrong type, or rejected
    3  Slack asked us to slow down
    4  the token works but lacks a scope this recipe cannot do without
"""

from __future__ import annotations

import json
import os
import sys
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

# Slack's own guidance for a large workspace, learned the expensive way on one:
# never enumerate the member list. Senders are resolved one at a time, cached
# for the run, and a failure to resolve one is cosmetic rather than fatal.
PAGE = 200


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
    allow at all. So the families are probed rather than assumed, once, and the
    answer is cached: re-probing every half hour is a rate limit waiting to
    happen.

    `im:history` is the floor. A recipe that cannot read the user's direct
    messages is not doing the job it claims to, so that one is fatal; the rest
    degrade to "skipped" and are reported.
    """
    identity = call("auth.test", token)
    available: list[str] = []
    missing: list[str] = []
    for family in FAMILIES:
        try:
            call("users.conversations", token, types=family, limit=1)
            available.append(family)
        except SlackError as exc:
            if exc.error in ("missing_scope", "not_allowed_token_type"):
                missing.append(family)
            else:
                raise
    return {
        "user_id": identity.get("user_id"),
        "team_id": identity.get("team_id"),
        "available": available,
        "missing": missing,
    }


def load_capabilities(token: str, *, refresh: bool = False) -> dict[str, Any]:
    path = capabilities_path()
    if not refresh and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("user_id"):
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


def read_cursors(conn) -> dict[str, str]:
    return {row[0]: row[1] for row in conn.execute(
        "SELECT scope, cursor FROM cursors WHERE source='slack'")}


def history(token: str, channel_id: str, oldest: str | None) -> list[dict[str, Any]]:
    """Messages since the watermark, oldest first.

    `oldest` is exclusive on Slack's side, so a repeated run re-reads nothing;
    `insert_items` is idempotent on `source_id` regardless, which is what makes
    a crash between the fetch and the commit harmless.
    """
    messages: list[dict[str, Any]] = []
    cursor = None
    while True:
        page = call("conversations.history", token, channel=channel_id,
                    oldest=oldest, inclusive="false", limit=PAGE, cursor=cursor)
        messages.extend(page.get("messages", []))
        if not page.get("has_more"):
            break
        cursor = (page.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    messages.sort(key=lambda m: float(m.get("ts", "0")))
    return messages


def sender_name(token: str, user_id: str | None, cache: dict[str, str | None]) -> str | None:
    """Resolve one display name, or give up quietly.

    A raw `U0…` id in a subject line is useless to a reader, but failing the
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


def collect(token: str, caps: dict[str, Any]) -> dict[str, Any]:
    ensure_store()
    channels = conversations(token, caps["available"])
    names: dict[str, str | None] = {}
    fetched = 0
    added = 0

    with write_txn() as conn:
        watermarks = read_cursors(conn)
        for channel in channels:
            messages = history(token, channel["id"], watermarks.get(channel["id"]))
            if not messages:
                continue
            items = [
                slack_message_to_item(
                    message, channel, caps["user_id"],
                    sender_name(token, message.get("user"), names))
                for message in messages
                # A message the user wrote is not a message they received.
                if message.get("user") != caps["user_id"]
            ]
            fetched += len(items)
            if items:
                added += insert_items(conn, items)
            # Advance past everything seen, including our own messages, so the
            # window never re-opens on them.
            conn.execute(
                "INSERT INTO cursors(source, scope, cursor) VALUES ('slack',?,?)"
                " ON CONFLICT(source, scope) DO UPDATE SET cursor=excluded.cursor,"
                " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (channel["id"], messages[-1]["ts"]))

    return {
        "conversations": len(channels),
        "fetched": fetched,
        "added": added,
        "skipped_families": caps["missing"],
    }


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
        result = collect(token, caps)
    except SlackError as exc:
        return _report_failure(exc)

    print(json.dumps(result))
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
