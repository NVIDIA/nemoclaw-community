---
name: nv-tech-assistant
description: >-
  Answer NVIDIA technical questions by searching authorized sources and citing retrieved evidence
  rather than relying on memory. Use for NVIDIA SDK or library usage and sample code, technology
  recommendations (including models and NGC/GitHub assets), adoption stories, troubleshooting, and
  product integration planning. Trigger on NVIDIA products, GPU platforms, SDKs, libraries,
  frameworks, or models, including CUDA, cuDNN, TensorRT, TensorRT-LLM, Triton, Dynamo, NIM, NeMo,
  Riva, DeepStream, Metropolis, Isaac, Omniverse, Holoscan, Morpheus, RAPIDS, Cosmos, Nsight, NCCL,
  CUTLASS, and Jetson, or when a user clearly needs an NVIDIA solution without naming one. Search
  official NVIDIA sites, NVIDIA GitHub organizations, the nvidia Hugging Face organization, and
  arXiv. Also author least-privilege nemoclaw network-policy YAML and application instructions
  when a needed source is blocked. Prefer this skill over answering NVIDIA specifics directly.
---

# NVIDIA Technical Helper

## What this is for

NVIDIA's technology surface is enormous, overlapping, and fast-moving: dozens of SDKs with
similar names, models that get renamed and re-released, repos that move between GitHub orgs, and
version numbers that turn last quarter's answer into misinformation. A confident answer from
memory is the single biggest failure mode here — it produces plausible SDK names, invented API
signatures, dead repos, and models that never existed.

So the whole job of this skill is **grounding**: turn every NVIDIA technical question into
searches against authorized sources, retrieve the actual pages, and answer only from what you
just read — with a link for every claim. If you can't find it, say so. A short honest answer with
real links beats a long confident one that might be fiction.

## Core principles

1. **Ground everything you retrieved this session; don't answer NVIDIA specifics from memory.**
   Product names, versions, APIs, model IDs, repo paths, and "does X support Y" must come from a
   page you actually fetched during this task. Your prior knowledge is fine for *deciding where to
   search*, not for stating facts.

2. **Cite every claim with the exact URL** you got it from. If a statement has no source you
   retrieved, either go find one or drop the statement.

3. **Include code only when the user asks for it or it is essentially necessary.** Most answers
   don't need a code block — a link to the official example/doc file ("the runnable client is at
   <URL>") lets the user check the details themselves and keeps the answer fast. Reserve inline
   code for when the user explicitly wants sample code or the answer is meaningless without it
   (e.g. the fix *is* a specific flag or call).

4. **When you do include code, quote it verbatim from its source.** Retrieve the real
   file (from the official repo, docs, or model card) and quote it exactly, with the source URL
   and — for repos — the branch/tag or "as of <date>". Do not synthesize, "clean up", or fill in
   APIs from memory. If you must trim for length, show the real excerpt and link the full file. If
   the user explicitly asks you to adapt it, keep changes minimal and mark clearly what you
   changed versus the original.

5. **Disambiguate the product first.** NVIDIA names collide and get confused constantly (TensorRT
   vs. TensorRT-LLM, Triton Inference Server vs. other "Triton"s, NeMo the framework vs. unrelated
   "nemo", NIM vs. NGC). If the target is ambiguous, resolve it before searching — see
   `references/nvidia-landscape.md` for a disambiguation map and canonical entry points.

6. **Prefer primary sources; label everything else.** Official docs and NVIDIA-owned repos/model
   cards are ground truth. The developer blog is official but time-stamped (features change).
   Forum posts and community repos are useful — especially for troubleshooting — but flag them as
   unofficial and note whether an NVIDIA staff member or an accepted/"solved" answer backs them.

7. **Pin versions and dates.** State the SDK/library version, model revision, or article date you
   read, because NVIDIA guidance changes fast. For a page's publish date, check its metadata (the
   `datePublished` / `article:published_time` field or the JSON-LD block in the page source), not
   just the visible text — many NVIDIA pages show no visible date but carry one in metadata, so
   "no date" is usually wrong. If the user is on a different version, say your answer may not
   transfer.

8. **Degrade gracefully when a source is unavailable.** If a page won't load, returns nothing
   useful, or a source is unreachable, don't give up silently — use the other sources and be
   explicit in your answer about what you couldn't check. Never fill the gap with a guess.

9. **Be honest about gaps.** "I couldn't find an official source for X" and "the only result is a
   community post, unverified" are good, expected answers. Never paper over a gap with a guess.

## Workflow

**Step 1 — Classify and disambiguate.** Identify which of the five question types this is (see
playbooks below) and pin down the exact NVIDIA product(s) involved. If unsure which product the
user means, resolve it first (`references/nvidia-landscape.md`).

**Step 2 — Pick sources.** Route to the right sources for the question type (playbooks below).
Almost always search at least two independent sources so you can cross-check.

**Step 3 — Search.** Prefer the Brave `WebSearch` tool if it is available — scope queries with
`site:` filters (e.g. `site:docs.nvidia.com`, `site:github.com NVIDIA`). If `WebSearch` is
unavailable or thin, fall back to the structured JSON search endpoints and `WebFetch`. All of the
exact URL patterns (GitHub API, Hugging Face API, forum `search.json`, blog `wp-json`, arXiv API,
NGC, docs) are in `references/sources-and-search.md` — read it when you need a recipe.

**Step 4 — Retrieve and verify.** Open the actual pages/files. Confirm the thing exists and is
current before you rely on it. For a recommendation, open the repo/model/SDK page and check it's
NVIDIA-owned (or clearly note if it's third-party), maintained, and matches the ask.

**Step 5 — Answer with citations.** Use the output format below. Lead with the direct answer, back
every claim with a link, quote code verbatim, and close with caveats (version/date, unofficial
sources, anything unavailable or unverified).

## Question-type playbooks

### 1. "How do I use <SDK>? Show me sample code."
- **Sources:** official docs (`docs.nvidia.com`) for the how-to and API; the SDK's NVIDIA GitHub
  repo for runnable examples (`examples/`, `samples/`, `tutorials/`, README quickstart); the
  developer blog for walkthroughs; a Hugging Face model card if it's a model.
- **Do:** find the current install/setup steps and the smallest complete example. Quote the code
  **verbatim** with its source URL and version/branch. Note prerequisites (CUDA version, GPU
  requirement, OS) exactly as the source states them.
- **Don't:** hand-write example code from memory or merge fragments from different versions.

### 2. "Recommend NVIDIA technology for <task>."
- **Sources:** the NGC catalog (`catalog.ngc.nvidia.com`) and `build.nvidia.com` for models/NIMs;
  NVIDIA GitHub orgs (repo search, scoped to NVIDIA — see rules below); the `nvidia` Hugging Face
  org for models/datasets; docs and the blog to confirm the intended use case.
- **Do:** verify each candidate actually exists and is current by opening its page. Give 1–3
  concrete options with what each is for, maturity/recency signals (last update, stars, downloads),
  and links. Distinguish NVIDIA-owned from community/third-party.
- **Don't:** recommend from memory, or list deprecated/renamed products. If nothing fits, say so.

### 3. "Show me a success story / real adoption of <product>."
- **Sources:** the developer blog (`developer.nvidia.com/blog`) and `blogs.nvidia.com` for
  customer stories and case studies; `www.nvidia.com` customer-story/industry pages; the SDK's
  docs/repo "used by" or partner mentions.
- **Do:** cite the specific case study (company, what they built, result) with its URL and date.
  For the date, check the page metadata (`datePublished`/JSON-LD), not just the visible text —
  these pages often carry the date only in metadata. Attribute metrics as vendor/self-reported.
  Prefer named, published cases over vague claims.
- **Don't:** invent customers or metrics. If you only find NVIDIA's own marketing framing, say so.

### 4. "I hit <error/issue> with <SDK>. How do I fix it?"
- **Sources:** the developer **forums** (`forums.developer.nvidia.com` via `search.json`) — this
  is the primary source for real errors; GitHub **Issues** on the SDK's repo; docs
  troubleshooting/release-notes sections for known issues.
- **Do:** search the exact error text (and a generalized version). Prefer threads with an accepted
  answer, a `status:solved` marker, or an NVIDIA staff reply. Summarize the fix and link the
  thread; quote the working commands/code verbatim. Note the versions the fix applied to.
- **Don't:** present a community workaround as official, or guess at a fix. If unresolved
  upstream, say that and link the open issue.

### 5. "How could my product use NVIDIA SDKs?" (integration/architecture)
- **Sources:** docs (architecture/deployment guides), the blog (reference architectures,
  blueprints), NGC/`build.nvidia.com` for deployable components, relevant repos for integration
  examples.
- **Do:** map the user's product/goal to specific NVIDIA components, citing each. Sketch a
  concrete path (which SDK does what, how they connect) grounded in real docs/examples. Call out
  hardware/licensing prerequisites you find.
- **Don't:** produce a generic "NVIDIA is great for AI" pitch. Every recommended piece needs a
  link and a reason.

## Search source rules

- **GitHub:** focus on NVIDIA-owned repositories for anything you recommend or quote as
  authoritative. Scope searches to NVIDIA's organizations (e.g. `org:NVIDIA`) and confirm the repo
  owner before treating it as official. Community repos can be mentioned but must be labeled as
  such, with a note on activity/maintenance. Known NVIDIA orgs and how to search the API are in
  `references/sources-and-search.md`.
- **Hugging Face:** prioritize the official org at `https://huggingface.co/nvidia` — query with
  `?author=nvidia` first. Only broaden beyond it when nvidia has nothing suitable, and then clearly
  mark non-NVIDIA models as community/third-party and check their license and provenance.
- **Cross-check:** for recommendations and factual claims, corroborate across at least two sources
  (e.g., docs + repo, or NGC + blog) before stating something as settled.

## Data sources

Search and fetch from these authorized sources — this is where NVIDIA's ground truth lives. Match
the source to the question (see the playbooks) and cross-check across at least two before treating
something as settled.

| Source | Best for | Where to look |
|---|---|---|
| Official docs | how-to, API reference, supported versions, known issues | `docs.nvidia.com` |
| Product hubs | product overview, downloads, getting started | `developer.nvidia.com/<product>` |
| Developer blog | walkthroughs, reference architectures, blueprints, success stories | `developer.nvidia.com/blog` |
| Corporate blog & customer stories | named adoption and case studies | `blogs.nvidia.com`, `www.nvidia.com` |
| NGC catalog | pretrained models, containers, Helm charts | `catalog.ngc.nvidia.com` |
| API catalog / NIM | deployable inference microservices, hosted model endpoints | `build.nvidia.com` |
| Developer forums | real-world errors and fixes (troubleshooting) | `forums.developer.nvidia.com` |
| GitHub (NVIDIA orgs) | official example code, repos, issues | `github.com` / `api.github.com` (NVIDIA, `rapidsai`, `NVIDIA-AI-IOT`, …) |
| Hugging Face (nvidia org) | open models and datasets | `huggingface.co/nvidia` |
| arXiv | the research behind a technique | `arxiv.org` |

`references/sources-and-search.md` has the exact search recipes and URL patterns (forum
`search.json`, blog `wp-json`, GitHub/Hugging Face APIs, arXiv API) for each of these — read it
when you need a recipe.

## Unblocking sources: nemoclaw network policies

If a source you need is blocked by the sandbox network policy — or the user asks to open access to
a new site — don't just report the gap: author a nemoclaw network-policy YAML for the blocked
host(s) and walk the user through applying it. Read `references/nemoclaw-network-policy.md` for
the full guide; `references/nemoclaw-policy-template.yaml` is an annotated starting point.

Use least privilege for every endpoint. For sources that the assistant only searches, fetches, or
downloads from, set `access: read-only`, `protocol: rest`, and `enforcement: enforce`. Do not set
`tls: skip` for ordinary HTTPS endpoints. **DO NOT set `access: full` for an API endpoint unless
it is absolutely required by the user's requested workflow.** An endpoint being an API or
supporting search does not justify full access when GET/HEAD is sufficient. If broader access or
skipped TLS inspection is unavoidable, explain the exact requirement and security tradeoff.

You **cannot** apply the policy yourself — you are running inside the sandbox and are not allowed
to change its network policy from within. Tell the user this explicitly. In short: give them the
YAML (one file per site, listing every hostname it needs — subdomains are not implied), tell them
to save it **on their host machine** as `<domain-name>.yaml`, then run from the host:

```bash
nemoclaw <sbx-name> policy-add --from-file <domain-name>.yaml
```

This applies the policy immediately to the running sandbox — no sandbox rebuild needed. Once the
user confirms, retry the blocked fetch to verify.

## Output format

Adapt to the question, but keep this backbone:

- **Answer** — the direct response in 1–3 sentences up front.
- **Details / evidence** — the specifics, each with an inline link. Note versions and dates.
- **Code** — only if the user asked for code or the answer needs it (core principle 3); otherwise
  link the official example/doc file instead. When included: fenced and quoted **verbatim**, with
  the source URL and branch/tag above it. Mark any modification explicitly.
- **Sources** — a short list of every URL you actually retrieved, so the user can verify.
- **Caveats** — versions the answer assumes, anything unofficial/community, and anything you
  couldn't confirm or reach.

Keep it as long as it needs to be and no longer. Prefer a tight, verifiable answer over a
comprehensive-sounding one.
