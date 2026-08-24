<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Set Up Slack

This connects the scheduled intake to the Slack messages you receive: direct
messages, group DMs, and any public channels you name. It is read-only. The
recipe never posts, never reacts, and never joins anything.

See the [recipe README](../README.md) for what the assistant then does with
those messages.

## What holds the credential

The OpenShell gateway does, and it refreshes it. Slack rotates user tokens: the
access half lasts twelve hours and each refresh token can be spent once. The
sandbox never receives the credential — it receives a placeholder that the
egress proxy substitutes on the way to `slack.com`, so the collector handles a
string it cannot spend.

Nothing outside the gateway may refresh this credential. A second refresher
does not fail loudly; Slack allows a spent refresh token to work for a short
grace period, so the two chains diverge quietly and surface days later as an
expired token with no obvious cause.

There is no supported path without the gateway. A token in the profile's
`.env` would abandon that custody, and with rotation on it would stop working
in twelve hours with nothing to renew it.

## The one thing that goes wrong

Slack has two kinds of token, and only one can see your direct messages.

- A **user token** acts as you. It sees what you see.
- A **bot token** acts as the app. It sees only conversations the app was
  invited into — never your DMs.

Using a bot token produces no error. It produces an assistant that quietly
never mentions anything anyone sent you. Three things prevent it: the bundled
manifest requests user scopes and no bot scopes, so the app has no bot token at
all; the setup script takes the refresh token from `authed_user.refresh_token`
by name rather than by position; and the collector checks the token's prefix
before it spends a call.

## Where each step runs

| Step | Runs | Needs |
| --- | --- | --- |
| `scripts/install.sh` | **inside the sandbox** | `hermes` |
| `scripts/setup-slack.sh` | **on the host** | `openshell` |

A NemoClaw sandbox has `hermes` and no `openshell`; the host has `openshell`
and no `hermes`. Because the gateway holds the credential, configuring it from
outside the sandbox is the design rather than a workaround.
`setup-slack.sh` detects being run in the wrong place and says so.

## 1. Create the app

Go to <https://api.slack.com/apps> → **Create New App** → **From a manifest**,
pick your workspace, and paste
[`slack_app_manifest.json`](slack_app_manifest.json).

The manifest turns **token rotation on**. Leave it on. Enabling it cannot be
undone, which is deliberate: a user token that never expires is a permanent key
to your entire Slack, and the gateway is what keeps this one short-lived. The
collector refuses a non-rotating token for that reason rather than because it
would not work.

### What it asks for, and why

| Scope | For |
| --- | --- |
| `im:read`, `im:history` | Your direct messages. Without these the recipe has no job. |
| `mpim:read`, `mpim:history` | Group DMs. |
| `channels:read`, `channels:history` | The public channels you name. |
| `users:read` | Turning `U04AB…` into a name a person can read. |

Private channels are **not** requested. `groups:read` / `groups:history`
commonly need workspace-admin approval, and asking for a scope your admin
refuses can cost you the whole install rather than that one scope.

## 2. Hand it to the gateway

**On the host**, from the recipe root:

```bash
bash scripts/setup-slack.sh
```

It looks first: if a provider exposing `SLACK_USER_TOKEN` is already attached
to your sandbox, it reuses it and changes nothing. It deliberately does not
reuse a provider whose credential key is `SLACK_BOT_TOKEN` or
`SLACK_APP_TOKEN` — Hermes removes those names from the environment of the
subprocesses it spawns, so such a provider attaches cleanly and delivers
nothing the collector can read. `providers/slack-user.yaml` carries the command
to check that list on your own install.

Otherwise it asks for the app's Client ID and Client Secret, prints an
authorization URL, and takes back the `code` from it.

**There is no "Install to Workspace" button for this app.** That button
installs a bot, and this app has no bot user. A user-scopes-only app is
authorized by opening the URL directly, which the script prints for you. The
page it redirects to will fail to load — the target is the IANA-reserved
example domain, so nobody receives your code and it stays visible in the
address bar where you can copy it.

The script then exchanges the code, takes the refresh token from
`authed_user.refresh_token`, registers the provider profile, creates the
provider, configures rotation, and attaches it to your sandbox. Attaching works
on a sandbox that already exists; it does not have to be rebuilt.

To replace the credential later — after regenerating the app's tokens, or if
the refresh chain broke:

```bash
FORCE_REAUTH=1 bash scripts/setup-slack.sh
```

## 3. Choose which channels to read

Direct messages and group DMs need no list; they are yours by definition. Public
channels are read only when you name them, in `workspace/slack_channels.json`
inside the profile home:

```json
{ "channels": ["C0TEAM0001", "C0PROJECT2"] }
```

This is not a convenience. Slack documents one request per minute and fifteen
messages per response for `conversations.history` on affected non-Marketplace
apps, so a workspace sweep cannot finish inside a scheduled tick — it spends
the window being throttled and then discards the work. Naming channels is what
makes coverage bounded, and it also keeps the recipe from collecting far more
than the job needs.

## 4. Verify

The collector runs inside the sandbox, so run it there:

```bash
openshell sandbox exec --name <sandbox> -- \
    python3 <profile home>/scripts/ingest_slack.py --recheck
```

Running it on the host reports `unconfigured`: the placeholder is injected into
the sandbox, not into your shell, so that tells you nothing.

A working run prints one line of JSON — how many conversations it considered,
how many it served this tick, how many messages were fetched and how many were
new, plus anything it could not reach.

`--recheck` re-probes what the token can do. The answer is cached in
`workspace/slack_capabilities.json`, because asking every half hour is a rate
limit waiting to happen. Re-run with `--recheck` after changing scopes.

Renewal is the gateway's:

```bash
openshell provider refresh status <provider> --credential-key SLACK_USER_TOKEN
```

### When it fails

The scheduled path deliberately drops a collector's output rather than writing
it to a job log — see [the README](../README.md#when-a-collector-fails) — so
the diagnosis rides in the exit code. Run it by hand to read the explanation.

| Exit | Meaning |
| --- | --- |
| `0` | Fetched, or never configured. Never configured is a state, not a fault. |
| `2` | Configured before and the credential has gone, is the wrong type, was rejected, or `slack.com` was unreachable. |
| `3` | Rate-limited. The next tick resumes from the same watermark. |
| `4` | The token works but lacks a scope the recipe needs. |
| `1` | Anything else. |

Two worth naming:

- **`slack.com` unreachable.** `nemohermes <sandbox> policy list` shows what is
  applied; look for a `●` beside `slack`, and add it with
  `nemohermes <sandbox> policy add slack` if it is `○`. **Do not check this
  with `curl`** — on the sandbox this recipe was measured against, `curl`
  returns `CONNECT tunnel failed, response 403` while the collector's own
  request to the same URL returns HTTP 200. The egress proxy treats the two
  clients differently, and not by `User-Agent`. Use the collector.
- **Exit `4` naming `im:history`.** The app installed with fewer scopes than it
  asked for, which an admin can do. Add them, reinstall, re-run with
  `--recheck`.

## What the schedule does with it

Nothing extra to configure. `select_intake.py` runs this collector before every
intake tick, and `scripts/register-jobs.sh` already scheduled that.

A tick is bounded, and where it starts rotates, so every conversation is
reached within a few ticks rather than the first few being served forever. What
a tick could not reach is reported as `incomplete_coverage` rather than left to
look like an absence of messages.

Once connected, a failure here is not silent: a collector that exits non-zero
wakes the agent even when nothing is pending, so a credential that stops working
shows up as a run rather than as an absence of runs.

## Revoking

Uninstalling the app from your workspace revokes the token. Then remove the
provider, which removes the stored credential with it:

```bash
openshell sandbox provider detach <sandbox> <provider>
openshell provider delete <provider>
```
