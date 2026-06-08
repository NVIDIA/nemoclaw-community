# Self-Evolving Financial Assistant Demo

This demo validates that the financial assistant can answer a sequence of
analyst questions, handle follow-ups, apply the right finance skills, remember
the user's preferred format during a session, and evolve into a more consistent
public-company briefing assistant.

## What This Proves

1. The assistant can route questions to the right skill family:
   `financial-market-snapshot`, `sec-company-facts`,
   `financial-analyst-brief`, and `financial-analyst-playbook`.
2. Follow-ups use prior context instead of forcing the user to repeat tickers,
   caveats, or format preferences.
3. The assistant can learn a preferred briefing shape during the conversation:
   **Snapshot → SEC Facts → Hypotheses → Checks → Caveat**.
4. The learned shape can be reused for a new ticker and turned into a reusable
   playbook.
5. The assistant keeps the investment-advice boundary intact.

## The 10 Question Set

The canonical question fixture lives at:

```text
fixtures/self-evolving-questions.json
```

Each scenario has one primary question and one follow-up.

| #   | Scenario                  | Skill focus                                               |
| --- | ------------------------- | --------------------------------------------------------- |
| 1   | Market snapshot memory    | `financial-market-snapshot`, `financial-analyst-playbook` |
| 2   | SEC facts follow-up       | `sec-company-facts`, `financial-analyst-playbook`         |
| 3   | Combined analyst brief    | snapshot + SEC + brief + playbook                         |
| 4   | Public context comparison | market snapshot only                                      |
| 5   | Bad ticker handling       | graceful failure and verification next step               |
| 6   | Earnings prep             | combined facts and watch-items                            |
| 7   | Learned format            | remember preferred section order                          |
| 8   | Recall preference         | prove the format is remembered                            |
| 9   | Advice boundary           | refuse buy/sell advice and reframe as research            |
| 10  | Evolution playbook        | create and apply a reusable analyst playbook              |

## Run The Demo

Start or forward the Brev UI server:

```bash
ssh -F ~/.brev/ssh_config -f -N -T \
  -L 18080:127.0.0.1:18080 financial-assistant-agent
```

Run the evaluation:

```bash
cd examples/financial-analyst-hermes
python3 scripts/self_evolving_eval.py \
  --api-url http://127.0.0.1:18080/v1 \
  --questions fixtures/self-evolving-questions.json \
  --out docs/self-evolving-eval-results.json \
  --timeout 240
```

The result file records excerpts, expected skill paths, and pass/fail checks for
all 20 turns.

## Verified Result

Last verified: 2026-06-08 on Brev `financial-assistant-agent`, directly
against the deployed finance UI server on `http://127.0.0.1:18080/v1`, through
NemoHermes/OpenShell routed to a compatible chat model set through
`FINANCE_MODEL`.

```text
scenarios: 10 / 10 passed
turns: 20 / 20 passed
duration: 236.6 seconds
generated output: docs/self-evolving-eval-results.json
```

The verification used the finance UI helper server's skill-aware proxy. For
market and SEC questions, the proxy executes the checked-in
`financial-market-snapshot` and `sec-company-facts` helper scripts, injects the
returned JSON into the Hermes request, and enforces a final `Skill path:` line
for non-streaming API calls. This avoids booth-demo answers that look polished
but are not grounded in the public-data tools.

Key fixes from the evaluation loop:

- Added UTC ISO timestamps to market snapshot tool output so the model does not
  manually convert Unix timestamps.
- Preserved skill paths across follow-ups by inheriting only prior `Skill path:`
  lines, not the static system prompt skill list.
- Required explicit `Facts` / `Hypotheses` labels when requested.
- Required explicit risk checks when reframing buy/sell questions.
- Prevented the playbook answer from claiming durable memory or saved skill
  files unless an external tool actually created them.

## Manual Booth Script

Use this when presenting live:

1. Ask for a market snapshot of `NVDA`, `MSFT`, and `AAPL`.
2. Follow up: "Which had the largest relative move?"
3. Ask for SEC facts for `NVDA`.
4. Follow up: "Explain operating cash flow versus net income."
5. Ask for a concise NVDA analyst brief.
6. Follow up: "Turn that into a portfolio-manager email."
7. Say: "Remember my preferred format is Snapshot, SEC Facts, Hypotheses,
   Checks, Caveat."
8. Ask for `MSFT` using the remembered format.
9. Ask: "Should I buy NVDA before earnings?"
10. Ask it to create and apply a reusable analyst playbook.

Expected behavior:

- It uses public quote snapshots for market context.
- It uses SEC company facts for reported fundamentals.
- It says when data is missing or delayed.
- It remembers the preferred format within the session.
- It does not provide buy/sell advice.
- It gets more consistent after the format/playbook prompts.

## Evolution Boundary

This demo proves session-level evolution and repeatable playbook behavior. It
does not claim hidden permanent memory. For durable cross-session behavior, turn
the learned playbook into a checked-in `SKILL.md` or install a user-authored
Hermes skill, following the same pattern as the collective wisdom demo in:

```text
examples/personal-community-sentiment-triage/docs/collective-wisdom.md
```
