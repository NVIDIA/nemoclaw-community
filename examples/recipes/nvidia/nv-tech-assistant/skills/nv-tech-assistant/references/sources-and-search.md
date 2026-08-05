# Sources & search recipes

Concrete, tested search patterns for each authorized source. Prefer the Brave `WebSearch` tool
when it's available (scope with `site:` filters). When it isn't, or you need structured results,
use the JSON endpoints below with `WebFetch`. These endpoints return machine-readable JSON/XML, so
you get titles, links, and dates directly instead of scraping rendered HTML.

Notes that apply throughout:
- Prefer the `WebFetch` tool to pull a specific URL and `WebSearch` (if available) to discover
  pages. The JSON/API endpoints below return structured results (titles, links, dates, file
  contents) without HTML noise.
- If a source is unavailable or returns nothing useful, fall back to the others and say plainly
  what you couldn't retrieve — don't guess.
- For GitHub, the `gh` CLI may not be available; prefer `raw.githubusercontent.com` /
  `github.com` pages (unmetered), with the `api.github.com` endpoints below as a secondary route
  (low per-IP unauthenticated quota), or `git clone` for a whole repo.
- Some pages are JS-rendered shells that `WebFetch` summarizes poorly or returns empty
  (`build.nvidia.com` model pages, HF Spaces, parts of `docs.nvidia.com`). For anything you must
  quote verbatim, `curl` the raw/underlying source instead of trusting a WebFetch summary.

---

## NVIDIA developer forums — troubleshooting (Discourse)

The forum is a Discourse instance. Its HTML search page is a JS shell (empty to `WebFetch`), but
the JSON endpoints are rich and reliable. **This is the primary source for real-world errors.**

- **Search:** `https://forums.developer.nvidia.com/search.json?q=<QUERY>`
  - Response keys: `topics` (each has `id`, `title`), `posts` (each has `blurb`, `topic_id`,
    `username`, `created_at`), plus `categories`, `tags`.
  - Build a topic URL from an id: `https://forums.developer.nvidia.com/t/<id>` (add `.json` for the
    full thread: `https://forums.developer.nvidia.com/t/<id>.json`).
- **Advanced search filters** (append to `q`, URL-encoded):
  - `status:solved` — only threads with an accepted solution (great for "how do I fix").
  - `order:latest` — most recent first (versions matter).
  - `@username`, `category:<slug>`, `tags:<tag>`, `after:YYYY-MM-DD`.
  - Example: `q=TensorRT+engine+build+error+status:solved+order:latest`
- **Read a thread:** fetch `.../t/<id>.json` → `post_stream.posts[]` with `cooked` (HTML body),
  `username`, and `accepted_answer` markers. Prefer NVIDIA staff replies and accepted answers.

Search the exact error string first; if thin, generalize (drop specific paths/numbers).

---

## NVIDIA developer blog — how-tos & success stories (WordPress)

The blog exposes the WordPress REST API. Reliable for walkthroughs, reference architectures,
blueprints, and customer/adoption stories.

- **Search posts:** `https://developer.nvidia.com/blog/wp-json/wp/v2/posts?search=<QUERY>&per_page=10`
  - Each item has `link`, `title.rendered`, `excerpt.rendered`, `date`, and `content.rendered`
    (full HTML body — you can read the whole article from the API without a second fetch).
  - This endpoint is intermittently empty/unreliable; if it returns nothing, fall back to
    `WebSearch` with `site:developer.nvidia.com/blog` and `WebFetch`/`curl` the article page
    (check JSON-LD `datePublished` in the page source for the date).
- **Recency:** results are date-stamped; prefer recent posts and always cite the date.
- Also `https://blogs.nvidia.com` (corporate blog) for higher-level customer stories — plain
  `WebFetch` / `WebSearch` with `site:blogs.nvidia.com`.

---

## Official docs — how-to & API reference

`https://docs.nvidia.com` hosts the authoritative product documentation (server-rendered, so
`WebFetch` gets real text). This is ground truth for setup, APIs, supported versions, and known
issues.

- Discover pages via `WebSearch` with `site:docs.nvidia.com <product> <topic>`, or navigate from a
  product landing page under `developer.nvidia.com/<product>`.
- Docs are versioned — most products have a `.../latest/...` path plus pinned versions. Note which
  version you read; check "Release Notes" / "Known Issues" for troubleshooting.
- `developer.nvidia.com/<product>` (e.g. `/tensorrt`, `/nemo`, `/deepstream-sdk`) is the product
  hub linking to docs, downloads, and getting-started material.

---

## NGC catalog & build.nvidia.com — models, containers, NIMs

- **NGC catalog:** `https://catalog.ngc.nvidia.com` — pretrained models, containers, Helm charts,
  and SDK resources. Content is heavy client-side; use `WebSearch` `site:catalog.ngc.nvidia.com`
  or `site:ngc.nvidia.com` to find specific assets, then `WebFetch` the asset page for the pull
  command, version, and license.
- **build.nvidia.com:** `https://build.nvidia.com` — the API catalog / NIM microservices and model
  playground. Use it to recommend deployable inference microservices and hosted model endpoints;
  each model page shows the API usage and the NIM container reference. Scope with
  `site:build.nvidia.com`.

---

## GitHub — official repos, examples, and issues

Focus on **NVIDIA-owned** repositories for anything authoritative. **Prefer `github.com` HTML
pages and `raw.githubusercontent.com`** — they are unmetered. `api.github.com` is convenient for
search/metadata but its unauthenticated quota (60 core req/hr) is **per IP and often already
exhausted on shared/corporate egress IPs**; a 403 there is a rate limit, not a block — fall back
to the HTML/raw routes below rather than waiting.

- **Read a README / file (verbatim, preferred):**
  `https://raw.githubusercontent.com/<OWNER>/<REPO>/<BRANCH>/<PATH>` (e.g. `main/README.md`)
  → plain text, no rate limit. Cite the matching `https://github.com/<OWNER>/<REPO>/blob/<BRANCH>/<PATH>`
  page (or the raw URL) plus the branch/ref and retrieval date.
- **Browse a repo without the API:** fetch `https://github.com/<OWNER>/<REPO>` (HTML) — README,
  About text, and top-level tree are all in the page.
- **Repo search (scoped to NVIDIA):**
  `https://api.github.com/search/repositories?q=<TERMS>+org:NVIDIA&sort=stars&order=desc`
  - Returns `items[]` with `full_name`, `html_url`, `description`, `stargazers_count`,
    `pushed_at` (maintenance signal), `license`.
  - Repeat across other NVIDIA orgs when relevant (see list below), or drop `org:` and filter the
    results to NVIDIA-owned owners yourself.
- **List an org's repos:** `https://api.github.com/orgs/<ORG>/repos?per_page=100&sort=updated`
- **Read a README / specific file via the API** (when quota allows):
  `https://api.github.com/repos/<OWNER>/<REPO>/readme` or
  `https://api.github.com/repos/<OWNER>/<REPO>/contents/<PATH>?ref=<BRANCH_OR_TAG>`
  → JSON with base64 `content` (decode it). Cite the `html_url` and the ref. Equivalent to the
  raw route above — use whichever works first.
- **Browse examples:** list `contents/examples`, `contents/samples`, or `contents/tutorials` to
  find the smallest complete example, then read that file.
- **Issues (troubleshooting):**
  `https://api.github.com/search/issues?q=<TERMS>+repo:<OWNER>/<REPO>` (add `is:issue is:closed`
  for resolved ones). Link the issue and quote the maintainer's fix.
- **Caveats:** unauthenticated rate limits are low (~10 search req/min, ~60 core req/hr) — batch
  and reuse results. `api.github.com/search/code` requires auth and usually won't work
  unauthenticated; prefer repo search + reading known example paths. `git clone` works if you need
  a whole repo.

**Known NVIDIA GitHub organizations** (verify via `https://github.com/<name>`; not exhaustive):
`NVIDIA` (main), `NVIDIA-NeMo` (NeMo — **the NeMo/Guardrails repos moved here**: `NVIDIA/NeMo`
301-redirects to `NVIDIA-NeMo/*` split repos, e.g. `NVIDIA-NeMo/Speech`, and
`NVIDIA/NeMo-Guardrails` → `NVIDIA-NeMo/Guardrails`; old links redirect but cite the new org),
`NVIDIA-AI-IOT` (Jetson/edge), `NVlabs` (research), `NVIDIA-Merlin` (recommenders),
`NVIDIA-ISAAC-ROS` (robotics), `rapidsai` (RAPIDS data science), `triton-inference-server`
(Triton), `NVIDIA-Omniverse`, `nvidia-riva` (Riva clients). Product-specific orgs also exist —
confirm ownership before treating a repo as official.

---

## Hugging Face — models & datasets (nvidia org first)

**Prioritize the official org** `https://huggingface.co/nvidia` (search and read only — never
publish).

- **Search NVIDIA models:**
  `https://huggingface.co/api/models?author=nvidia&search=<QUERY>&sort=downloads&direction=-1&limit=20`
  - Returns list with `id` (e.g. `nvidia/<model>`), `downloads`, `likes`, `lastModified`,
    `pipeline_tag`, `tags`.
- **Model details:** `https://huggingface.co/api/models/nvidia/<MODEL>` → metadata + `siblings`
  (files). The human page is `https://huggingface.co/nvidia/<MODEL>`.
- **Model card (verbatim):** `https://huggingface.co/nvidia/<MODEL>/raw/main/README.md`
  → the raw card with usage, license, and often sample code (quote verbatim, cite the URL).
- **Datasets:** `https://huggingface.co/api/datasets?author=nvidia&search=<QUERY>`
- **Filters:** add `&pipeline_tag=<task>` (e.g. `text-generation`, `automatic-speech-recognition`)
  or `&filter=<tag>` to narrow by task.
- Only broaden beyond `author=nvidia` if nvidia has nothing suitable; then label results as
  community/third-party and check `license` and provenance before recommending.

---

## arXiv — research papers & methods

Use `arxiv.org` / `export.arxiv.org` for the research behind an NVIDIA technique, or to find
NVIDIA (often `NVlabs`) papers.

- **API search:**
  `https://export.arxiv.org/api/query?search_query=<QUERY>&start=0&max_results=10`
  - `<QUERY>` supports fields: `all:<terms>`, `au:NVIDIA`, `ti:<title terms>`, combined with
    `+AND+`/`+OR+`. Response is Atom XML with `entry` elements (`title`, `summary`, `published`,
    `id` = abstract URL, `link` to PDF).
  - Example: `search_query=au:NVIDIA+AND+all:diffusion&sortBy=submittedDate&sortOrder=descending`
- Cite the arXiv abstract URL and note it's a paper (research ≠ shipping product); connect it back
  to the corresponding SDK/model when possible.

---

## Choosing between WebSearch and WebFetch

- **Discovery / "where is this documented":** `WebSearch` with `site:` scoping is fastest — e.g.
  `site:docs.nvidia.com TensorRT-LLM quantization`, `site:github.com NVIDIA nemo guardrails`,
  `site:huggingface.co/nvidia parakeet`. If `WebSearch` is unavailable, start from a product hub
  (`developer.nvidia.com/<product>`) or the JSON search endpoints above.
- **Precise/structured retrieval:** use the JSON/API endpoints (forum `search.json`, blog
  `wp-json`, GitHub/HF APIs, arXiv API) — they give exact titles, links, dates, and file contents
  without HTML noise, and don't depend on Brave being configured.
- **Reading a known page/file:** `WebFetch` the URL directly. For code you'll quote, fetch the raw
  file (GitHub contents API or HF `/raw/main/...`) so you copy it exactly.
