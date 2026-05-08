---
name: outlook-email-search
description: Search the Outlook mailbox via Microsoft Graph to find and read emails that help answer user questions.
---

# outlook-email-search

Use this skill to search emails and answer questions that require reading mail
— finding a specific message, summarizing a thread, checking whether something
was communicated, or pulling context from recent correspondence.

## When to use

- "Did I get an email about X?"
- "What did [person] say about [topic]?"
- "Summarize the emails about [project] from the last two weeks"
- "Check if [decision/approval/update] was sent to me"
- "Find unread emails from [sender]"
- "Are external developers discussing things not covered in our updates?"

## Access model

- All Graph API requests go through the credential sidecar at `$MS_GRAPH_SIDECAR_URL`.
- Use `Authorization: Bearer MS_GRAPH_TOKEN_PLACEHOLDER_OUTLOOK` — the sidecar swaps
  this for a live delegated token before forwarding to `graph.microsoft.com`.
- `MS_GRAPH_SIDECAR_URL` is already set in the environment; the helper script reads it.
- **Two mailbox env vars** — understand the distinction:
  - `OUTLOOK_REPLY_TO` — the **human owner's** personal address (e.g. `you@nvidia.com`).
    When the user says "my emails", this is what they mean. This is the
    primary target for search.
  - `OUTLOOK_TARGET_MAILBOX` — the **agent's** polling mailbox
    (e.g. `agt-you@nvidia.com`). The bridge monitors this for task requests.
    Only used as a fallback if `OUTLOOK_REPLY_TO` is not set.
  - The delegated token (from the agent account) has `Mail.ReadWrite.Shared`
    which grants read access to the human's mailbox via `/users/EMAIL/` in Graph.

## Procedure

### 1. Run the search helper

The scripts are at:
```
/sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py
/sandbox/.hermes-data/skills/outlook-email-search/scripts/get_thread.py
```

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/outlook-email-search/scripts/search_emails.py [OPTIONS]
```

**Options:**

| Flag | Description |
|------|-------------|
| `--query TEXT` | Free-text keyword search (KQL) — searches subject, body, sender |
| `--subject TEXT` | Subject contains this text |
| `--from EMAIL` | Exact sender email address |
| `--since DATE` | Messages after date (`2026-04-01`, or relative `7d`, `2w`, `1m`) |
| `--until DATE` | Messages before date |
| `--folder NAME` | `inbox` (default), `sent`, `drafts`, `archive`, `junk` |
| `--top N` | Max results (default 20, max 50) |
| `--unread` | Unread messages only |
| `--body` | Fetch full body text (makes one extra Graph request per message) |
| `--external-only` | Return only emails from senders **outside** the internal domain (auto-detected from `OUTLOOK_REPLY_TO`, defaults to `nvidia.com`) |
| `--domain DOMAIN` | Return only emails from senders at this specific domain |
| `--domain-not DOMAIN` | Exclude senders from this domain (repeatable) |
| `--pages N` | Follow `@odata.nextLink` up to N pages (default 1, max 5). Each page is up to 50 messages. Useful with `--external-only` to compensate for client-side filtering. |

At least one filter is required.

### 2. Interpret the output

The script returns JSON:
```json
{
  "ok": true,
  "count": 3,
  "messages": [
    {
      "id": "AAMk...",
      "subject": "Q1 budget approval",
      "from": "manager@nvidia.com",
      "from_name": "Jane Manager",
      "received": "2026-04-15T14:32:00Z",
      "is_read": false,
      "has_attachments": true,
      "preview": "Hi Matt, the Q1 budget has been approved...",
      "conversation_id": "AAQkADlh..."
    }
  ]
}
```

The `preview` field is the first ~250 characters of the body. Use `--body` when
you need the full text to answer the question. The `conversation_id` field is
used to fetch full threads (see below).

### 3. Fetch a full thread

When you need the complete back-and-forth of an email conversation, use
`get_thread.py` with the `conversation_id` from a search result:

```bash
/usr/bin/python3 /sandbox/.hermes-data/skills/outlook-email-search/scripts/get_thread.py \
  --conversation-id "AAQkADlh..."
```

This fetches all messages in the thread in chronological order with full body
text. Output:
```json
{
  "ok": true,
  "conversation_id": "AAQkADlh...",
  "count": 4,
  "messages": [
    {
      "id": "AAMk...",
      "subject": "Re: project update",
      "from": "partner@external.com",
      "from_name": "Alice Partner",
      "received": "2026-04-28T10:00:00Z",
      "body": "Thanks for the update. We've been seeing..."
    }
  ]
}
```

### 4. Fetch a specific message (if needed)

If the preview is not enough and `--body` would return too many results, fetch
one message directly:

```bash
# Replace USER@nvidia.com with the value of OUTLOOK_REPLY_TO
curl -s "${MS_GRAPH_SIDECAR_URL}/v1.0/users/USER@nvidia.com/messages/MESSAGE_ID?\$select=subject,body,from,receivedDateTime" \
  -H "Authorization: Bearer MS_GRAPH_TOKEN_PLACEHOLDER_OUTLOOK" | /usr/bin/python3 -c "
import json, sys, html, re
d = json.load(sys.stdin)
content = d.get('body', {}).get('content', '')
content = re.sub(r'<[^>]+>', ' ', content)
content = html.unescape(content)
print(re.sub(r'\s+', ' ', content).strip()[:5000])
"
```

### 5. Synthesize and answer

Read the results and answer the user's question directly. If no results were
returned, say so clearly rather than guessing. Suggest a broader search if the
criteria may have been too narrow.

#### Format for summary requests

When the user asks for a summary or overview of emails (not a specific lookup),
use this compact format — do not produce flowing prose:

```
**Inbox — {date}, {N} messages**

**{Category}**
- {Subject} ({Sender first name}) — {one-line takeaway}
- …

**{Category}**
- …

**Bottom line:** {2–3 sentence synthesis of the day's main themes.}
```

Rules:
- Category headers group related threads. Use 4–6 categories max; merge thin
  ones into "Other".
- Each bullet: subject (trimmed if long), sender first name only, em-dash,
  one-line takeaway. No nested bullets.
- Omit the verbose intro sentence ("Here's a summary of … based on … messages
  returned …"). The header line is enough context.
- Skip purely automated/bot messages (GitHub notifications, OTP codes, marketing
  newsletters) unless directly relevant to the user's question. Note how many
  were skipped if more than 5.
- Use "Bottom line:" not "Overall".

## Comparing external emails to internal meeting topics

Use this multi-step procedure to answer questions like "Are there external
developers discussing things that haven't come up in our daily updates this week?"

**Step 1 — Get the internal reference (meeting notes / daily updates)**

Search for the recurring update emails by subject pattern:
```bash
/usr/bin/python3 .../search_emails.py --subject "nemotron update" --since 7d --body --top 10
```
Extract the main topics mentioned: product areas, bugs, features, names.

**Step 2 — Get external emails on the same project**

```bash
/usr/bin/python3 .../search_emails.py --query "nemotron" --external-only --since 7d --pages 2 --top 30
```
If `--external-only` returns fewer results than expected, increase `--pages`.

**Step 3 — Read relevant threads in full**

For each external email that looks potentially new or interesting, read the
full thread to understand what is actually being discussed:
```bash
/usr/bin/python3 .../get_thread.py --conversation-id "AAQkADlh..."
```

**Step 4 — Compare and present the gaps**

List the topics appearing in external threads that were NOT mentioned in the
internal updates. Format:

```
**External discussions not covered in this week's updates:**
- [Topic X] — 3 messages from partner@external.com (thread started Mon)
- [Topic Y] — discussed by community@forum.org, unresolved

**Covered in both:**
- [Topic Z] — aligned
```

## Common patterns

**Find emails about a topic from this week:**
```bash
/usr/bin/python3 .../search_emails.py --query "budget approval" --since 7d
```

**What did a specific person send recently?**
```bash
/usr/bin/python3 .../search_emails.py --from person@nvidia.com --since 30d --top 10
```

**Unread emails with full body:**
```bash
/usr/bin/python3 .../search_emails.py --unread --body --top 10
```

**Search sent folder for something you sent:**
```bash
/usr/bin/python3 .../search_emails.py --query "project update" --folder sent --since 2w
```

**Check for a specific subject in a date window:**
```bash
/usr/bin/python3 .../search_emails.py --subject "Q1 report" --since 2026-04-01 --until 2026-04-30
```

**External senders only (e.g. community feedback):**
```bash
/usr/bin/python3 .../search_emails.py --external-only --since 7d --pages 2 --top 30
```

**All email from one external partner's domain:**
```bash
/usr/bin/python3 .../search_emails.py --domain partner.com --since 30d
```

**Read a full thread:**
```bash
/usr/bin/python3 .../get_thread.py --conversation-id "AAQkADlhN2..."
```

## Pitfalls

- `--body` is significantly slower — it makes one Graph request per message.
  Use it only when `preview` is insufficient.
- `--query` uses KQL full-text search; `--orderby` (newest first) is dropped
  when `--query` is active (Graph API constraint). Results are still relevant
  but not date-sorted.
- `--subject` and `--query` can be combined. Both are passed to Graph as KQL.
- `--from` uses OData `$filter` for an exact email match. Do not use it for
  partial name matching — use `--query "from:Name"` instead.
- `--external-only`, `--domain`, and `--domain-not` are **client-side** filters
  applied after Graph returns results. Graph always returns up to `$top=50` per
  page; use `--pages 2` or higher if you need many external results after filtering.
- Searches target the human's mailbox (`OUTLOOK_REPLY_TO`), not the agent's
  polling mailbox (`OUTLOOK_TARGET_MAILBOX`). The agent has delegated access to
  read the human's mail via `Mail.ReadWrite.Shared`.
- Do not claim Outlook is unavailable just because one search returns no results.
  Try a broader query or different date range first.
