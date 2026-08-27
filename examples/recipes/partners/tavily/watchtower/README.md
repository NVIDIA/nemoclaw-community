# Watchtower

Runs scheduled, cited web monitoring with deduplication and auditable outputs.

| Catalog field | Value |
| --- | --- |
| Industry | ✨ Other |
| Requirements | Docker · NemoClaw · Tavily and inference provider API keys · one-time operator.admin approval |
| Contributor | Tavily |

Watchtower is a NemoClaw community example for unattended web monitoring. It
runs as an auditable **OpenClaw Cron Job**, searches the web with Tavily,
extracts source text when needed, and writes a Markdown digest plus JSON
changelog.

This community example was contributed by [Tavily](https://tavily.com). For
questions or support, contact [support@tavily.com](mailto:support@tavily.com).

Use it when you want a sandboxed agent to periodically answer:

> What changed on the topics I care about, and does it matter?

## What it does

Each scheduled sweep:

1. Reads a watchlist from `watchlists/*.yaml`.
2. Searches each topic with Tavily `web_search`.
3. Drops URLs already recorded in `state/seen.json` and any explicitly excluded
   domains.
4. Uses `tavily_extract` for surviving URLs when snippets are not enough.
5. Judges relevance, source credibility, and significance.
6. Writes:
   - `outputs/digest-<run-id>.md`
   - `outputs/changelog-<run-id>.json`
7. Commits digested URLs to state only after outputs exist.

That last step matters: if a run crashes mid-sweep, the next run can safely
process the same candidates again instead of silently losing them.

## Quickstart

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/recipes/partners/tavily/watchtower

cp .env.example .env      # add TAVILY_API_KEY + inference credentials
bash scripts/onboard.sh   # create/configure the NemoClaw sandbox
bash scripts/install.sh   # upload the skill, watchlists, and prompt
bash scripts/start.sh     # request creation of the OpenClaw Cron Job
```

By default, `scripts/start.sh` creates a `watchtower-regulatory` job that runs
once every 24 hours. The schedule and run history are visible in the OpenClaw
Dashboard under **Cron Jobs**.

Creating or removing a Cron Job requires the `operator.admin` scope. NemoClaw
does not approve that scope automatically. On a fresh sandbox, the first
`scripts/start.sh` attempt prints the pending request and exits. Follow its
instructions to inspect and approve that exact request from
`nemoclaw watchtower connect`, then rerun `scripts/start.sh`. The approval is
stored for the paired CLI device, so normal status and lifecycle commands work
afterward.

## Requirements

- Docker and NemoClaw installed.
- `TAVILY_API_KEY` from <https://app.tavily.com>.
- A Nebius Token Factory API key from <https://tokenfactory.nebius.com/> for
  the default Nemotron 3 Ultra configuration, or credentials for another
  inference provider supported by NemoClaw.

See [`.env.example`](.env.example) for the exact variables.

## Commands

Run one sweep now:

```bash
bash scripts/sweep.sh
```

Run a different watchlist once:

```bash
bash scripts/sweep.sh watchlists/ai-policy.yaml
```

Create a scheduled job:

```bash
bash scripts/start.sh watchlists/regulatory.yaml 24h
bash scripts/start.sh watchlists/security-advisories.yaml 3h
bash scripts/start.sh watchlists/ai-policy.yaml 30m
```

Integer intervals are treated as seconds and converted for OpenClaw:

```bash
bash scripts/start.sh watchlists/regulatory.yaml 300   # 5m
```

Check scheduler status, recent runs, and latest outputs:

```bash
bash scripts/status.sh
```

Remove Watchtower cron jobs:

```bash
bash scripts/stop.sh
```

## Watchlists

A watchlist defines the topics to monitor and how to judge them.

```yaml
watchlist: regulatory
topics:
  - id: ofac-sanctions-designations
    query: "new sanctions designation specially designated nationals list update"
    seed_sources: [ofac.treasury.gov]
    exclude_domains: [wikipedia.org]
    lookback_days: 14
    why_it_matters: "New OFAC designations can immediately affect screening obligations and permissible counterparties"
```

Topic fields:

| Key | Required | Purpose |
|---|---:|---|
| `id` | yes | Stable topic identifier used in state, digests, and changelogs. |
| `query` | yes | Search intent, phrased for a web search engine. |
| `why_it_matters` | yes | The significance yardstick for the agent's judgment. |
| `seed_sources` | no | Source hints. The agent may use `site:` queries, but these are not a hard allowlist. |
| `exclude_domains` | no | Hard negative filter for noisy domains. Enforced by `diff_state.py`. |
| `lookback_days` | no | Recency hint for search queries. |

Included presets:

- [`watchlists/regulatory.yaml`](watchlists/regulatory.yaml) — EU PFAS updates,
  OFAC sanctions designations, and FDA device recalls.
- [`watchlists/security-advisories.yaml`](watchlists/security-advisories.yaml) —
  actively exploited vulnerabilities, cloud-native advisories, and open-source
  supply-chain attacks.
- [`watchlists/ai-policy.yaml`](watchlists/ai-policy.yaml) — AI regulatory
  enforcement, model-safety standards, and copyright litigation.

## Outputs and state

Watchtower writes outputs inside the sandbox workspace:

```text
outputs/digest-<run-id>.md
outputs/changelog-<run-id>.json
state/seen.json
```

Sample output is checked in under [`outputs/sample/`](outputs/sample/).

`state/seen.json` is the dedup ledger. Items are keyed by topic id and URL, so
multiple watchlists can share one state file safely as long as topic ids are
stable.

## How scheduling works

Watchtower uses OpenClaw-native Cron Jobs, not host cron and not a hidden
background loop. `scripts/start.sh` invokes the supported, paired `openclaw
cron add` CLI. It never claims or auto-approves administrative scopes. After
you explicitly approve the CLI device's exact `operator.admin` request, the
job is visible and auditable in the Dashboard.

Useful `.env` scheduling defaults:

```env
WATCHTOWER_WATCHLIST=watchlists/regulatory.yaml
WATCHTOWER_EVERY=24h
WATCHTOWER_TIMEOUT_SECONDS=900
WATCHTOWER_JOB_NAME=watchtower-regulatory
```

## Files to customize

```text
watchlists/*.yaml                    # monitored topics
agents.yaml                          # main-agent tool policy
prompts/AGENTS.md                    # agent behavior rules
skills/watchtower/SKILL.md           # sweep procedure
skills/watchtower/scripts/*.py       # validation, diff, and state commit helpers
```

Most users should start by editing or adding a watchlist, then run:

```bash
bash scripts/install.sh
bash scripts/sweep.sh watchlists/your-watchlist.yaml
```

## Security notes

- Tavily is the research path: search uses `web_search`; page extraction uses
  `tavily_extract`.
- [`agents.yaml`](agents.yaml) explicitly denies `web_fetch`; Tavily extraction
  remains available through `tavily_extract`.
- The Tavily key is stored by NemoClaw/OpenShell provider plumbing, not written
  into the watchlist or skill files.
- Dedup and `exclude_domains` are deterministic script checks, not model memory.
- State is committed only after digest and changelog files are written.
