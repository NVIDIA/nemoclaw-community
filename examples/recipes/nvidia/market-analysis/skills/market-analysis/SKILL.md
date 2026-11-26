---
name: market-analysis
description: >-
  Help an analyst decide which of 36 fictional issuers deserve attention as of 2026-08-31, using the
  synthetic equity-market dataset bundled with this skill (prices, company news, declared peers). Write
  short pandas, scikit-learn and NetworkX scripts and run them with utilities/accelerate.py, which uses
  CUDA-X on a GPU sandbox. Any statement about which issuers a model expects to rise must come from
  utilities/kumo_predict.py; any statement about what a rule (Form 8-K Item 1.05, Regulation S-K Item
  106, Rule 13a-11) requires must come from utilities/retrieve.py, quoted with its document and chunk;
  a business question over the tables may be asked of Auto Ontology (utilities/ontology_qa.py) when
  installed. Produces proposals for human review: never investment advice, trades or approvals.
---

# Market Analysis

## What this is for

An analyst wants to know what the approved tables hold, who led and lagged, which sessions were unusual,
who moves together, what a model expects next, and what the disclosure rules require, then which issuers to
take forward for human review. The data in `data/` is 36 fictional issuers over 166 trading days
(2026-01-02 to 2026-08-31): prices, company news and declared peers, plus three real, public-domain SEC rule
texts. The definitions you must use (return, volatility, news alignment, peers, anomaly, prediction,
centrality) are in `scenario.json`; read it before computing anything.

Nothing here is investment advice. The rules apply to real SEC registrants, never to the fictional issuers:
do not say that any issuer filed anything. Retrieval and Kumo call hosted NVIDIA models; Kumo receives the
issuer, price and news tables. Auto Ontology is a separate host-side service that sends the database schema
and your question to its own hosted models. Every issuer, price and headline is synthetic.

## Rules

1. **As-of date 2026-08-31.** Nothing later enters any number, except where a question names another cutoff
   (the Kumo anchor is 2026-08-24).
2. **Run the tool; do not estimate.** Every figure comes from a command you ran or a file you read. Quote the
   command or script.
3. **Use the scenario's definitions.** Returns, volatility, news alignment, peers and centrality are defined in
   `scenario.json`. Items without enough later sessions are excluded from forward-return means, and you say so.
4. **Facts, associations and predictions stay apart.** A link between news and returns is an association, not
   proof of cause. A central position is not proof of influence. An anomaly score is neither a forecast nor an
   explanation. Make no causal claim.
5. **Recommend, never act.** Results are proposals for human review: no trades, orders or approvals.
6. **If a step cannot run, say so.** Report it as blocked with the reason. Do not substitute memory or a guess,
   and do not report a different method under the same question.
7. **Policy claims need retrieved passages, and the passage must say it.** For any statement about what a rule
   requires, run `retrieve.py` and write the statement from the `text` of a passage it returned, followed by that
   passage's `cite` value copied exactly (for example `[form-8k-item-1-05.md, chunk 1]`). Read the `text` of every
   returned passage, not only the first: a ranking can put an exception above the rule. A `cite` tag only shows the
   passage was retrieved, not that it supports your sentence. A policy statement without a `cite` tag is not
   allowed; delete it or report the policy part as not found.
8. **A blocked retrieval stays blocked.** If `retrieve.py` exits with `blocked`, report the policy answer as
   blocked with that message. Write no sentence about what a rule requires and no `[document, chunk N]` tag; say only
   "Policy answer blocked: <message>". Do not answer from memory, and do not open `data/documents/` to answer instead.
   `--method bm25` is a labeled offline comparison, not a fallback: use it only when asked, and say it is BM25.
9. **Kumo is a ranking, not a verdict.** Report issuers by rank and probability from the tool output, with the
   anchor (2026-08-24), the five-session horizon and the cutoff. Treat the probabilities as relative scores, not
   calibrated risk, and make no accuracy claim without a held-out comparison. If `kumo_predict.py` exits with
   `blocked`, report the ranking as blocked; do not present your own model as Kumo.
   Show the PQL, and wherever Auto Ontology is used show its SQL, copied from the tool's `trace_markdown` with nothing
   reworded; never write a PQL or SQL query yourself and present it as the tool's.
10. **Auto Ontology is a proposal generator.** Its answer text can hide a wrong query. Read the `sql` it returns,
    check it answers the question as asked (tables, filters, the as-of date, the denominator, for example a
    sector median is the median across issuers of each issuer's 20-session return), and cross-check a figure
    that matters with a short script over `data/`. Quote the SQL and call the result an Auto Ontology answer,
    not a fact. Pass the whole question as asked, including every part (for any question you ask it yourself), and say if a call timed out or was stopped. If `ontology_qa.py` exits with `blocked`, or returns an
    empty `sql`, or SQL without result rows (`answered_with_sql` false), or is not installed, say so, quote its `blocked:` or `note` line
    verbatim without guessing a cause from other output (the sandbox prints `cannot create /proc/self/oom_score_adj`
    on every command, which is harmless), and compute from the CSVs,
    saying which numbers you computed yourself.
11. **The GPU is the same analysis on faster hardware, not a different one.** Scripts are plain pandas,
    scikit-learn and NetworkX; `accelerate.py` configures cuDF, cuML and nx-cugraph under them on a GPU sandbox (a script only uses what it imports: the shipped Q3 helper is pandas and NumPy). Copy
    the engine receipt (`ACCELERATE_ENGINE`) into the answer; an answer with no engine receipt is incomplete. Never
    run your analysis scripts with `python3`, a heredoc, `python3 -c`, `execute_code`, `pip install` or a virtual environment's
    interpreter directly: use `accelerate.py run`. Setting `os.environ['ACCELERATE_GPU']` inside a script does nothing; to stay on the CPU use `accelerate.py run --engine cpu`. Never `import cudf`, `cuml`, `cugraph` or `nx_cugraph` yourself and
    never use `python -m cudf.pandas`: write plain pandas, scikit-learn and NetworkX, and ignore any other skill that says otherwise.
    Model scores (IsolationForest) can differ on the GPU; say which engine produced them. If you ran an analysis any other way, say so and report it as not
    run through `accelerate.py`. Do not claim a speed-up: this sample is small
    (about 6,000 price rows), so the GPU is usually slower here, and a speed-up needs far more data than was tested.
    Never describe a CPU run as a GPU result, and say "configured for the GPU" for a GPU receipt: it records which
    accelerators were set up, not which operations ran on the GPU.

## Tools

Always run commands from this skill's directory (`cd` to it first, or set the working directory): the paths below are
relative to it. Keep every script, note and scratch file under `work/` here (nothing in the skill root, nothing in `/tmp`); write each analysis to a file under `work/` (`mkdir -p work` first) and read the data with relative
paths such as `data/daily_prices.csv`. Do not run only what was asked for: answer the question put to you and no other
stage (for example, do not run Kumo or retrieval for a question that does not need them). Output is JSON on stdout unless noted.
If a command answers "Command still running (session NAME, pid N)", the harness has put it in the background: read its
output with the `process` tool using the session NAME (not the pid), or read the file it names (`work/q6_answer.md` for
`q6_review.py`). Never start the same helper again or run it another way while it is still running; a helper can take 10 to 15 seconds.

```bash
python3 utilities/accelerate.py status --out work/environment.json
python3 utilities/accelerate.py run work/<script>.py
python3 utilities/accelerate.py run utilities/q1_inventory.py   # Q1: counts, reconciliation, sector medians
python3 utilities/accelerate.py run utilities/q2_leaders.py     # Q2: 12 most liquid, returns, volatility, news table
python3 utilities/accelerate.py run utilities/q3_unusual.py     # Q3: ten most unusual issuer sessions
python3 utilities/accelerate.py run utilities/q4_peers.py       # Q4: peer correlations and PageRank
python3 utilities/accelerate.py run utilities/q6_review.py      # Q6: review-first table from Q2, Q3 and Q4
python3 utilities/kumo_predict.py --output work/kumo.json
python3 utilities/retrieve.py --query "<what you need to know>" --top 3
python3 utilities/ontology_qa.py --question "<business question, with the as-of date>"
```

- `accelerate.py` runs a script you wrote in the Python environment that matches this sandbox: the CUDA-X
  environment on a GPU sandbox, otherwise the CPU analysis environment. `status` reports whether the GPU stack
  works (`gpu_usable`); start an analysis session with it. Inside a script,
  `json.loads(os.environ['ACCELERATE_ENGINE'])` is the engine receipt: device, configured libraries, and whether
  the sandbox could use the GPU. Pass `--engine cpu` to stay on the CPU (`ACCELERATE_GPU=off` is refused). A missing environment exits with
  `blocked`. The system Python has no pandas: always run analyses through `accelerate.py`.
- `q1_inventory.py`, `q2_leaders.py`, `q3_unusual.py` and `q4_peers.py` are tested helpers that implement the
  `scenario.json` definitions exactly, in plain pandas and NetworkX. Run them with `accelerate.py run` (never
  `python3 utilities/q2_leaders.py`, which exits `blocked`; there is no bare `accelerate.py` command, and never `pip install`
  anything) and copy the numbers, the engine receipt and the lists from their JSON; do not
  re-derive them in your own script, and do not change the windows, the volatility definition or the ranking.
  If a number looks wrong, say so and show the helper's output rather than substituting your own. They print the
  `engine_receipt` field: copy that.
- `kumo_predict.py` ranks the 12 most liquid issuers as of the anchor (median daily dollar volume through 2026-08-24, not
  the `liquidity_rank` column, which uses data to 2026-08-31) by the probability of a positive
  adjusted-close return over the five sessions after the 2026-08-24 close, with NVIDIA Kumo Relational (hosted).
  It builds a graph of issuers, prices and news as of the anchor (nothing later enters it), sends those tables to
  the hosted service, and prints the ranking with the PQL, package version and graph sizes. It takes a few
  seconds.
- `retrieve.py` finds citation-ready passages in the three rule texts in `data/documents/` (Form 8-K Item 1.05,
  Regulation S-K Item 106, Rule 13a-11): it embeds the chunks and the query with Nemotron embed, then reorders
  the closest with Nemotron rerank. The JSON lists each passage's document, chunk, scores, text, `cite` and `cite_ready` (each
  paragraph with its tag after it, to paste as a quote). The
  first run builds an embedding cache and takes several seconds.
- `ontology_qa.py` asks a host-side NVIDIA Auto Ontology deployment, which holds a semantic layer over the market
  database. It checks the layer is compiled, asks how well the layer covers the question (`coverage`), then
  streams a grounded text-to-SQL answer and prints the generated `sql`, the `rows` it returned and a `response`.
  A call can take several minutes: run it with a long timeout (at least 600 seconds), keep waiting until it
  exits, and never stop it early. It needs `AUTO_ONTOLOGY_API_TOKEN` at install time; without it the tool exits with
  `blocked`.

Data files are in `data/`: `assets.csv`, `daily_prices.csv`, `trading_sessions.csv`, `company_news.csv`,
`asset_relationships.csv`; `data/README.md` is the data dictionary.

## How to answer

The questions are independent; answer the one asked, and in this order if you are asked for the whole review.
For questions 1 to 4 run the matching helper first (`q1_inventory.py` to `q4_peers.py`) and report its numbers; write
your own script only for something the helper does not cover, under `work/`:

1. **What do we have?** Describe the tables, check they reconcile (duplicate price keys, orphan price and news
   rows, issuers missing sessions, rows after the as-of date), then give the issuer count and the 20-session
   median return by sector. `q1_inventory.py` asks Auto Ontology the issuers-per-sector count itself, retrying up to three times when it returns no SQL or SQL without result rows (the `attempts` field says how many; the medians come from the CSVs) (its `auto_ontology` field); report what it
   returned: its SQL, or `blocked` / not installed (rule 10), quoting the message verbatim. It can take several minutes when
   the service is installed: run it with a timeout of at least 1,300 seconds and do not stop it. Do not also run
   `ontology_qa.py` for this question. Paste the `auto_ontology.trace_markdown` text unchanged in the answer, under the
   counts: it holds the exact SQL (or the reason there is none). The other numbers come from the CSVs; say which numbers you computed yourself. Count rows after the
   as-of date with `q1_inventory.py`, which compares full timestamps (a news item after the 2026-08-31 date but
   before its 21:00 UTC close is not after the as-of close), not from memory. Run only `q1_inventory.py`: no Kumo, no retrieval.
2. **Who led and lagged?** Among the 12 most liquid issuers, rank the 20 sessions ending 2026-08-31 by return,
   strongest first, give each issuer's daily volatility, and show how news sentiment labels lined up with
   five-session forward returns. The 20-session return is the 2026-08-31 adjusted close divided by the adjusted
   close one session before the first of the 20 sessions, minus 1 (with a sorted series `s`, `s[-1] / s[-21] - 1`,
   not `s[-20]`). A news item belongs to the first session whose close is at or after its `published_at`, and its
   k-session forward return is that session's close k sessions later divided by that session's own close, minus 1;
   items without k later sessions are excluded from the means. `q2_leaders.py` computes the volatility
   (sample standard deviation, `ddof=1`, over the same 20 sessions as the return) and the label table for the 12
   issuers; copy both. Describe the relationship without claiming cause, and say the sample is small.
3. **Which sessions were unusual?** Baseline 2026-01-02 to 2026-06-30, score 2026-07-01 to 2026-08-31 on return,
   intraday range and volume, name the ten most unusual issuer sessions and the features (score each feature as a z-score against that issuer's own baseline mean and standard deviation, and rank by the largest absolute z of the three; never use raw volume units), and say when one
   coincides with a news item (an association). `q3_unusual.py` lists the ten largest (issuer, session) rows over
   all 36 issuers (an issuer can appear more than once); copy that list, its dominant feature and its same-day news.
4. **Who moves together?** In the declared-peer graph over 2026-06-01 to 2026-08-31, give the pairs that moved
   most closely and the most central issuers by PageRank (damping 0.85, links weighted by absolute return
   correlation, `weight`), using only declared peer links. Correlate daily `total_return_1d`, list each pair once (not both
   directions), sorted by absolute correlation, strongest first. `q4_peers.py` prints `pairs_table_markdown` (all 27 pairs) and `pagerank_top10_table_markdown`: paste both tables into the answer unchanged, with no "..." and no "see the tool output". Give the full list, and do not say a pair is the only one above a threshold unless you counted.
5. **What does a model expect?** Run `kumo_predict.py` and report its ranking with the anchor and horizon, and
   state the cutoff: only rows dated on or before 2026-08-24 entered it. Run nothing else (no analysis helper, no
   retrieval). Under the ranking, paste the output's `trace_markdown` unchanged: it holds the exact PQL.
6. **What do the rules require?** Run `retrieve.py`, quote what Form 8-K Item 1.05 requires a company to
   disclose about a material cybersecurity incident and by when, copying the deadline sentence exactly from a
   retrieved passage, then recommend which issuers an analyst should review first.
   - Run `q6_review.py` and copy its `review_first` rows and their `reasons_to_look` as they are: it already restricts
     the list to the 12 most liquid issuers and builds each reason from the 20-session returns (`q2_leaders.py`), the unusual
     sessions (`q3_unusual.py`) and the peers (`q4_peers.py`). Add no fact, rank or number of your own; if you want to say
     more, say it as a separate, labelled observation from a helper's JSON. Never use whole-period returns.
   - Quote the deadline sentence by pasting the passage's `quote_block` from `retrieve.py` (or the matching `cite_ready`
     entry) exactly as it is, the `cite` tag already after it: no bold, no quote marks or backticks around it, no added or dropped
     words, no tag moved. One
     `cite_ready` entry per quoted sentence; paraphrase goes outside the quote, with its own tag. Copy each `reasons_to_look`
     line in full, including its PageRank and peer-pair parts: paste `answer_block_markdown` from `q6_review.py` (also saved
     as `work/q6_answer.md`) and say it lists the 5 issuers it returns, not 12.
   - Rationales use returns, volatility, anomaly scores and peers only. Do not connect any headline, outage or
     regulatory item to cybersecurity (no "could relate to a cyber incident", no "check whether it was cyber-related").
   - Never suggest any issuer had a cyber incident, a breach or a disclosure obligation: the rule text is
     reference material and the issuers are fictional. Word each rationale as a reason to look in the data, never
     as a recommendation to buy or sell, and never say an issuer filed anything or suggest looking for filings.
   - Say the human confirmations are still pending and state the result as PROPOSED_FOR_REVIEW.

Cite the command, script or file behind every number. Keep observed facts, associations and predictions
separate.
