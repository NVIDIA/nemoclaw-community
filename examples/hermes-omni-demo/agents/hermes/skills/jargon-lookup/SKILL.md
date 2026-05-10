---
name: jargon-lookup
description: Look up technical jargon and terminology on whitelisted knowledge sources (Wikipedia and Free Dictionary API). Use when the user asks to define, explain, or look up a term, or asks to "search Wikipedia" for any topic. This is the ONLY working path to Wikipedia from the sandbox — do not use browser tools or curl.
version: 1.0.0
metadata:
  hermes:
    tags: [wikipedia, dictionary, lookup, reference, knowledge]
---

# Jargon Lookup

Look up technical terms on Wikipedia (primary) or the Free Dictionary API (fallback). Both sources are whitelisted by the NemoClaw policy; all other knowledge sources are blocked.

## CRITICAL — this script is the ONLY way to reach Wikipedia

The NemoClaw policy blocks:
- `browser_navigate` and every other browser tool
- `curl`, `wget`, and any shell HTTP client
- Every website except Wikipedia's summary API and the Free Dictionary API

If the user says "search Wikipedia", "look it up", "what is X", "define X", "find info on X" — run `lookup-jargon.py`. Do not refuse with "I can't browse the web" — you can, via this script. Do not answer from training knowledge first; always run the script and present what it returned.

## How to invoke

Via the terminal tool (NOT execute_code):

```bash
python3 /sandbox/.hermes-data/workspace/lookup-jargon.py "TERM"
python3 /sandbox/.hermes-data/workspace/lookup-jargon.py "TERM" --context "DOMAIN"
python3 /sandbox/.hermes-data/workspace/lookup-jargon.py "term1" "term2" "term3" --json
```

## Context disambiguation

Many short technical terms collide with more popular non-technical meanings. Wikipedia's default page for a bare word is often wrong for the user's intent. **Always pass `--context`** when you know the domain.

| Term | Without context | With `--context "machine learning"` |
|------|----------------|-------------------------------------|
| `transformer` | Electrical device | Transformer (deep learning) |
| `CNN` | News channel | Convolutional neural network |
| `attention` | Psychology | Attention (machine learning) |

| Term | Without context | With `--context "physics"` |
|------|----------------|----------------------------|
| `tensor` | Disambiguation | Tensor |
| `kernel` | Disambiguation | (context-appropriate physics page) |

Derive the context from what the user is talking about. If they just analyzed a physics lecture → pass `--context "physics"`. If an ML paper → `--context "machine learning"`.

## Output formats

- Default: human-readable with title, source, definition, URL
- `--json`: machine-readable JSON array of result objects

## Blocked-site behavior

If the user asks to look something up on Google, Stack Overflow, or anywhere else not whitelisted, **actually try it** (e.g., `curl https://google.com`) so the user can SEE the NemoClaw block with a 403 Forbidden. Do not refuse upfront — demonstrate the block, then fall back to `lookup-jargon.py` on Wikipedia.
