<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Set Up Slack

This connects the scheduled intake to the Slack messages you receive: direct
messages, group DMs, and the public channels you are in. It is read-only. The
recipe never posts, never reacts, and never joins anything.

See the [recipe README](../README.md) for what the assistant then does with
those messages.

## The one thing that goes wrong

Slack hands out two kinds of token from the same page, and only one of them
can see your direct messages.

- A **user token** (`xoxp-`) acts as you. It sees what you see.
- A **bot token** (`xoxb-`) acts as the app. It sees only the conversations the
  app was invited into — never your DMs.

Pasting the bot token does not produce an error. It produces an assistant that
quietly never mentions anything anyone sent you directly. The bundled manifest
avoids the choice entirely: it declares user scopes and no bot scopes, so the
app has no bot token to confuse yours with. The collector also checks the
prefix and refuses a `xoxb-` by name.

## Prerequisites

- A Slack workspace you can install an app into. Some workspaces require an
  admin to approve app installation; if yours does, you need that approval
  before the token exists.
- Linux, including WSL. See [Requirements](../README.md#requirements).

## 1. Check whether you already have one

If this machine has run another NemoClaw recipe, a Slack credential may already
be attached to the sandbox:

```bash
bash scripts/setup-slack.sh
```

It looks first and exits without changing anything if it finds a provider that
exposes `SLACK_USER_TOKEN`. Only if it finds none does it ask you for a token.

It deliberately does **not** reuse a provider whose credential key is
`SLACK_BOT_TOKEN` or `SLACK_APP_TOKEN`. Hermes strips those two names from
every subprocess it spawns, cron pre-steps included, so such a provider
attaches cleanly and delivers nothing the collector can read. The script says
so when it skips one rather than leaving you to debug an empty result.

## 2. Create the app from the bundled manifest

Only if step 1 asked you for a token.

1. Go to <https://api.slack.com/apps> and choose **Create New App** → **From a
   manifest**.
2. Pick your workspace.
3. Paste the contents of
   [`slack_app_manifest.json`](slack_app_manifest.json).
4. Review and create.

The manifest sets `token_rotation_enabled: false`. Leave it that way. This
recipe supports static user tokens only, and **enabling rotation on a Slack app
cannot be undone** — the access token would then expire within hours and
nothing here refreshes it. The collector rejects a rotating token (`xoxe.xoxp-`)
rather than working for one afternoon and then going quiet.

### What it asks for, and why

| Scope | For |
| --- | --- |
| `im:read`, `im:history` | Your direct messages. Without these the recipe has no job. |
| `mpim:read`, `mpim:history` | Group DMs. |
| `channels:read`, `channels:history` | The public channels you are in. |
| `users:read` | Turning `U04AB…` into a name a person can read. |

Private channels are **not** requested. `groups:read` / `groups:history`
commonly need workspace-admin approval, and asking for a scope your admin
refuses can cost you the whole install rather than just that one scope. If you
want them, add both to the manifest's `oauth_config.scopes.user` and add
`"private_channel": "groups:history"` to `FAMILIES` in
`profile/scripts/ingest_slack.py`.

## 3. Install it and copy the User token

1. **OAuth & Permissions** → **Install to Workspace** → approve.
2. Copy **User OAuth Token**. It starts with `xoxp-`.

That page shows the bot token too, lower down. You want the one above it.

## 4. Hand it over

Re-run the setup script and paste the token when it asks:

```bash
bash scripts/setup-slack.sh
```

It stores the token in the OpenShell gateway and attaches the provider to your
sandbox. The sandbox itself only ever sees a placeholder — the real token is
substituted by the egress proxy on the way to `slack.com`, so the collector
handles a string it cannot spend.

Attaching works on a sandbox that already exists; you do not have to rebuild
it.

**No OpenShell on this machine?** Put the token in the profile's `.env`
instead:

```bash
echo 'SLACK_USER_TOKEN=xoxp-...' >> "$(hermes profile show memory-driven-chief-of-staff | sed -n 's/^Path:[[:space:]]*//p')/.env"
```

That file is never copied by the installer and never travels with the profile.

## 5. Verify

```bash
python3 profile/scripts/ingest_slack.py --recheck
```

A working run prints one line of JSON — how many conversations it saw, how many
messages it fetched, how many were new, and which conversation families your
workspace did not grant.

`--recheck` re-probes what the token can do. The answer is cached in
`workspace/slack_capabilities.json`, because asking every half hour is a rate
limit waiting to happen. Re-run with `--recheck` after changing scopes.

### When it fails

The collector exits with a code that says which kind of problem it is, because
the scheduled path deliberately drops a collector's output rather than writing
it to a job log — see [the README](../README.md#when-a-collector-fails). Run it
by hand to read the explanation.

| Exit | Meaning |
| --- | --- |
| `2` | Credential: absent, wrong type, rejected, or `slack.com` unreachable. |
| `3` | Rate-limited. The next tick resumes from the same watermark. |
| `4` | The token works but lacks a scope the recipe needs. |
| `1` | Anything else. |

Two failures worth naming:

- **`slack.com` unreachable.** The sandbox's egress policy has to allow it.
  `nemohermes <sandbox> policy list` shows what is allowed;
  `nemohermes <sandbox> policy add <preset>` adds one.
- **Exit `4` naming `im:history`.** The app installed with fewer scopes than it
  asked for, which an admin can do. Add them, reinstall the app, and re-run
  with `--recheck`.

## What the schedule does with it

Nothing extra to configure. `select_intake.py` runs this collector before every
intake tick, and `scripts/register-jobs.sh` already scheduled that. Until this
setup is done the collector is simply absent, and the schedule runs over
whatever is already in the store.

Once it is connected, a failure here is *not* silent: a collector that exits
non-zero wakes the agent even when nothing is pending, so a token that stops
working shows up as a run rather than as an absence of runs.

## Rotating the token

If you regenerate the token in Slack, hand the new one over the same way:

```bash
bash scripts/setup-slack.sh
```

It updates the existing provider rather than creating a second one. Nothing
else needs restarting — the collector reads the credential fresh on every tick.
