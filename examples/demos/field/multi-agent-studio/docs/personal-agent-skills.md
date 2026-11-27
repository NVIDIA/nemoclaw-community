# Personal-agent skill demo

Hiring exposes seven shipped skills: Live weather, Tech Radar, Web research, Coding, Slack announcements, Data interpretation and UX design. An agent can also be hired without a custom skill for ordinary conversation. Three Takeaways and Personal memory remain supported for existing profiles. These are not downloaded marketplace packages or independent tool engines. OpenClaw discovers the selected SKILL.md files; the adapter separately grants the tools they need. Specialist work requires an equipped skill that covers it, even when the role text matches. Tool permissions and optional OpenShell policies enforce access separately.

| Skill | Short demonstration | Evidence to inspect |
| --- | --- | --- |
| Tech Radar | Hire and connect the model; the first Heartbeat starts after at least 10 seconds, then checks every 20 seconds. | One unread technical article per check; persona-based summary in the agent’s Lounge chat. [Setup](heartbeat.md). |
| Web research | Find three recent arXiv RAG preprints and choose one to read first. | Submission dates, authors, abstract links, query and retrieval date; abstract-based comparison, not a claimed full-paper review. |
| Live weather | Ask whether an outdoor break is a good idea in the chosen city. | MET Norway forecast for the resolved city, with local time, units and attribution. If no forecast is available, the agent reports the gap without switching providers. |
| Data interpretation | Upload a sales CSV and ask which stores grew year over year. | A comparison tied to the supplied rows and figures, with missing values identified. |
| Coding | Create and play a reaction-time game. | Actual self-contained HTML file and isolated preview; no external libraries/network. |
| Slack announcements | Ask for an announcement or a personal reaction; get an emoji-led headline and short lines. | Chat drafts in the chosen tone; unknown facts remain TBC; no Slack connection or posting. |
| UX design | Ask for a layout for a small dashboard. | A design brief with a clear reading order, controls and accessibility considerations. |

For a short presentation, try a city forecast with Live weather or a CSV comparison with Data interpretation. In Hiring, a preset selects its core skill. You can add other skills or use **Suggest skills** after writing a custom role. Casey assigns work according to the skills and tools each hire has.

Use **Add a document** or drop files onto an agent’s chat. PDF, PPTX, XLSX, TXT, Markdown and CSV files share a 10 MB per-file limit. The document list above the conversation belongs to the selected agent and persists across reloads; PDF/PPTX/XLSX text companions are hidden from that list. Wait for active work to finish before uploading, so OpenShell workspace synchronization cannot overwrite the new file. OpenShell agents read their uploads from their own sandbox workspace. Standard mode uses separate workspaces and app-scoped file access, but does not provide OS-level isolation from the host.

Save text documents as UTF-8; invalid encodings are rejected before upload instead of replacing unreadable characters. Names such as `report.pdf.txt` are reserved while `report.pdf` exists, to protect its extracted text. If a separate text document already has that name, rename the incoming PDF/PPTX/XLSX before uploading. Re-uploading the original binary document refreshes its own extracted text.

Role and tone are independent of skill authorization. Changing Cynical to Kind should change expression, not weather facts or paper citations. Run all agents compares personal responses through the queue; each needs the relevant skills and permissions for a fair capability comparison.

## Research without a paid search key

Protected Open Task web research uses a 40-second cap for each sandboxed retrieval command, separate from the overall assignment budget. Its instructions use `timeoutSeconds:40` and `curl --max-time 40`; this is not a global limit for every hired-agent shell command. A tool argument error is not an OpenShell policy denial. Hired agents retain their own policy when joining Open Task; verified denied destinations produce the shield and **Request blocked** notice at the agent's current location, and remain available in that agent's **OpenShell Policy** panel.

Standard Web research can use Parallel Search without an API key. Parallel receives the search objective and search terms and may retain or use them. Keep personal and confidential information out of searches. OpenShell agents read permitted URLs inside their own sandbox. [Parallel legal and privacy information](https://parallel.ai/legal)

When search is unavailable, paper discovery tries the [arXiv API](https://info.arxiv.org/help/api/user-manual.html) once, with a small result count, a valid fielded query and descending submission-date sort. On a timeout, 429, 406 or other API failure, it switches to arXiv's static `/list/<category>/recent` pages, selects a bounded set of relevant entries and reads their `/abs/<id>` pages. It does not retry the API, use unverified model memory or call the dynamic `/search` page as a fallback. It checks at most two category lists and three abstracts, and reports that limited coverage. Search requires a ready configured runtime, and source availability is not guaranteed. A query's newest results are not necessarily the world's newest or best papers. Preprints are not automatically peer reviewed.

With OpenShell on, **arXiv papers** is a separate, initially unapproved permission for read-only HTTPS to `export.arxiv.org` and `arxiv.org` through sandboxed curl. Equipping research does not approve those hosts. Policy denial and upstream failures are different: approving a destination does not fix API rate limits. Never bypass a denial.

The Programmer/Coding skill favors a compact desktop page or game, a working saved file and focused follow-up changes. Web research favors short cited answers and saves a brief only on request or for a team handoff. Protected researchers can write briefs inside their workspace while network permissions remain unchanged. Neither skill is a general browser-control or code-execution environment.

## Registration

Profiles and selected skill IDs persist at Hiring; workspace definitions are written at Hiring. Protected agents and Tech Radar warm their native runtime in the background; other agents register on the next Run. Open Task specialists receive separate role definitions and native identities. Source of truth: `scripts/agent_runtime.py::SKILLS` and `register()`. `src/studio.js` provides the matching capability cards and example requests. Existing IDs are preserved so saved agents do not lose their loadouts. Restarting the app refreshes the in-process registration cache; the next run rewrites the equipped skill instructions. Restart also invalidates session-only credentials.

## Persona transparency

**Instructions** keeps three editable panels for AGENTS.md, IDENTITY.md and SOUL.md. Click the agent name/portrait to edit all displayed files, including equipped skills and memory, in **Agent Files**. Use **Save changes** while the agent is idle; Instructions saves its three files and keeps other file drafts for Agent Files. Switching files keeps drafts; explicit saves survive workspace preparation and app restarts. Custom file instructions take precedence over generated persona defaults on subsequent tasks, without granting skills or tool permissions. **Edit agent** still controls the displayed profile, equipped skills and model. **Files** shows the files you attached to that agent. Open generated files from the chat reply or from Open Task **Results**.

The editor’s Tone and Role are written verbatim into SOUL.md (outer whitespace is trimmed; internal line breaks are preserved). Preset buttons insert their visible label and description. Bare words such as Cynical are not secretly expanded. The separate Shared boundaries section asks the agent to follow that persona while avoiding severe profanity, abuse, hate/threats, invented evidence and permission bypass. Tool/security instructions remain in AGENTS.md and the equipped skills; they are not hidden personality rewrites. Existing native files update on the next run after restart or profile edit.

Role shortcuts are Weather buddy, Tech Radar, arXiv researcher, Slack writer, Programmer, Web researcher and Data analyst. Each preset fixes its corresponding core skill; extra skills remain editable. Saving through the API also restores that core skill, and startup repairs older preset profiles that lack it. Switching roles releases the previous lock; custom roles may have no skills. Tech Radar's role is read-only to keep its schedule aligned with its skill, and manual chat is disabled while that skill is equipped. See [Heartbeat](heartbeat.md).

Quick missions request short answers: weather bullets, three papers with a comparison, three numbered takeaways, or an emoji-led draft. These are requested output bounds, not latency guarantees. Three Takeaways and Personal memory remain supported for existing profiles but are hidden from the current Hiring picker.

## In-character detours

The literal user-authored Tone and Role remain unchanged in `SOUL.md`. Shared guidance allows ordinary conversation, simple reasoning and adjacent help, but requires a brief refusal for a substantive deliverable not covered by an equipped skill. A relevant skill is required for specialist work; role text, tone, an explicit name and tool availability cannot replace it. Refusals should explain the missing expertise in the chosen voice and distinguish a role mismatch from missing tools, unavailable sources and an observed policy denial. Exact compliance still depends on the model; this is not an access-control boundary.

## Closing personal reactions

After an Open Task result is ready, one randomly chosen eligible hire who did not work on it gets up to 30 seconds to react, within the remaining task time. Use **Retry reaction** if the agent times out, or **Ask another agent** to hear from another available hire. Both actions use the saved result.

The separate “Personal opinions” guidance in `SOUL.md` asks the model to choose its subject from the saved role and interests, then express it in the saved tone. The roundtable follows the same rule: matching a friendly or cynical voice is not sufficient if the subject ignores the character. Shared interests stay valid; two weather agents should find different observations within that interest instead of one turning into a robotics reviewer.

Guests take turns and receive the completed earlier comments as untrusted conversation context. Each successful guest still makes one model call; there are no canned lines, assigned booth topics, keyword-based rewrites or extra diversity-judge calls. For Open Task, the host supplies the request, final response, completion status, remaining requirements and bounded specialist summaries. A partial result stays partial; personal comments do not replace independent review. Failed guests do not block the next speaker; retrying one includes completed comments without regenerating them. Existing saved reactions are unchanged. This short closing conversation is sequential; specialist work follows the selected Open Task plan.

## Demo: role, skill and access are different

- A Weather buddy with Live weather can investigate weather for a trip, but should decline a request to build a game, even when named explicitly.
- Add Coding and the same agent can build a small game while retaining its voice. Its skill now covers the assignment; no general all-purpose permission was added.
- A custom developer without Coding must decline implementation. The Programmer preset supplies Coding as a fixed skill. Skill-free hires still support ordinary conversation; a role description does not substitute for a missing skill.
- Public research still requires a permitted retrieval tool. OpenShell-on agents need approval for each relevant destination. A missing tool, a role/skill mismatch, and a policy denial are distinct explanations.
- Greetings, simple explanations and small adjacent requests remain possible; scope checks are for substantive assignments, not every sentence.

Casey checks equipped skills and then actual tools. Role text and names do not substitute for a missing skill. Selected hires include a short `roleFit` explanation in the plan. Unsuitable named hires can be listed with an explicit decline reason, so validation does not force them back into the team. A specialist may also decline an out-of-scope assignment; it stops without pretending a missing file is merely a failed write to repair. These semantic decisions still depend on the model following its instructions; they are not a security sandbox.

The Hiring cards keep skill descriptions short. After hiring, Agent Files exposes the equipped SKILL.md instructions. Protection-specific transport and runtime instructions are added to that agent's workspace; reading or editing guidance does not grant new permissions.

## Recognizable reply formats

Three Takeaways uses exactly three numbered points for personal chat, clarifying questions, capability limitations and Open Task reactions. Any next step belongs inside those three points. Slack announcements uses a relevant emoji headline and short lines, preserving the chosen tone rather than making every agent cheerful. With both skills, the response has three numbered, emoji-led points and no separate heading. Crew artifact contracts retain their required formats.

The same signature rules are read from the project SKILL.md into personal SOUL.md and included in both chat and reaction prompts. The app displays the model's answer; it does not manufacture three points or insert emoji after generation. These remain model instructions, not a guarantee that every model will comply. Existing preset roles are migrated by exact text match; custom role/tone text and memory are preserved. The independent brief idle bubbles are authored UI flavor, not model responses or a skill execution trace.

Three Takeaways can also read user-supplied public links. Standard agents use native `web_fetch`; protected agents use sandboxed curl and require approval for the destination. The three-point response format remains the same.
