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

## 0. Encrypted storage

Attaching this connector is the moment real message bodies start landing in the
store, and the prerequisite is that the profile home sits on an encrypted
volume. The setup script checks what it can and asks you to confirm the rest.
See [`encrypted-storage.md`](encrypted-storage.md) for how to verify it and
what to do if the answer is no.

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
authorized by opening the URL directly, which the script prints for you.

The redirect target is a **loopback** address, and that matters. Slack sends
the authorization code to whatever redirect URI the app declares — it is a
real HTTP request carrying a real credential, so the destination has to be
somewhere only you can reach. A loopback URL sends it to your own machine and
nowhere else. The page will fail to load because nothing is listening there;
the code is still visible in the address bar, which is where you copy it from.

Do not point this at a domain you do not operate. A documentation-example
domain is not an exception: those are reserved for use in examples, not
unserved, and a request sent to one reaches somebody else's web server.

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

### Threads, and what the bound costs

A thread reply does not appear in `conversations.history` — only the parent
does, and only while it is inside the window being read. Once the channel
watermark passes a parent, Slack never returns it again. So a thread that is
still alive needs its own watermark, and a parent with no replies yet needs to
be checked occasionally in case a first one arrives.

Both are bounded, and the bounds are worth knowing because they are the
difference between "collected everything" and "collected what a scheduled tick
can afford":

- A channel remembers its **200 most recent** parents for that check. A first
  reply to something further back than that is not discovered. Parents that
  already have replies are remembered regardless of age, since forgetting one
  would re-read the whole thread.
- Each tick checks **eight** of the watched parents, starting where the last
  tick stopped, so a busy channel reaches all of them within a few ticks
  rather than serving the oldest forever. Threads that are known to have
  replies are always read first; only those hold the channel watermark back.

Neither bound loses a message that has already been collected. They decide how
quickly a *new* reply to an *old* thread is noticed, which on a half-hourly
schedule is a few ticks rather than immediately.

Naming a channel decides what is read. Deciding what is *never stored* is a
separate list, `workspace/exclusions.json`, which takes senders, domains and
channels and is applied before any row is written — so a colleague you would
rather not keep, or a channel where pay is discussed, never lands on disk even
though the DM or channel it arrived in is being read. See
[data-lifecycle.md](data-lifecycle.md).

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

That ends the collection. It does not remove what was already collected: the
messages read up to that point are still in the store. `python3 reset.py --yes`
removes them along with the memory and the learned policy, and
`python3 export_store.py` writes out a copy first if you want one. Both are in
[data-lifecycle.md](data-lifecycle.md); revoking and erasing are separate
actions and doing one is easy to mistake for both.
