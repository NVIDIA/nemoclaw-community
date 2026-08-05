# Writing and applying nemoclaw network policies

Use this when a source you need is blocked by the sandbox network policy (fetches fail or return
policy-block errors), or when the user asks to open access to a new site. The fix is a small YAML
policy file plus one `nemoclaw` command run on the host — no sandbox rebuild.

**Important: you cannot apply the policy yourself.** You are running inside the sandbox and are
not allowed to change its network policy from within. Your job is to author the YAML content and
give the user exact instructions; the user must save the file and run the command **on their host
machine**. Say this explicitly so the user doesn't wait for you to do it.

## 1. Write the policy YAML

Start from `references/nemoclaw-policy-template.yaml` (annotated). Present the finished YAML to
the user in a fenced code block so they can copy it.

Structure, using arXiv as an example:

```yaml
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

preset:
  name: arxiv                      # unique id, kebab-case, matches the file name
  description: "arXiv access"      # one-line summary

network_policies:
  arxiv_access:                    # policy key
    name: arxiv_access
    endpoints:
      - host: arxiv.org            # one entry per hostname — subdomains are not implied
        port: 443
        access: read-only          # allow only GET/HEAD
        protocol: rest
        enforcement: enforce
      - host: export.arxiv.org
        port: 443
        access: read-only
        protocol: rest
        enforcement: enforce
    binaries:                      # sandbox binaries allowed to use these endpoints
      - { path: /usr/local/bin/node* }
      - { path: /usr/bin/node* }
```

Field notes:

- **`endpoints`** — list every hostname explicitly; allowing `example.com` does not allow
  `api.example.com`. Port is almost always 443.
- **`access`** — default to `read-only` for search, fetch, and download hosts. This permits
  GET/HEAD and blocks writes. **DO NOT set `access: full` for an API endpoint unless it is
  absolutely required by the user's requested workflow.** An endpoint being an API or supporting
  search does not justify full access when GET/HEAD is sufficient. If full access is unavoidable,
  identify the exact write method the workflow requires and explain why read-only access cannot
  satisfy it.
- **`protocol` and `enforcement`** — use `protocol: rest` with `enforcement: enforce` so the
  endpoint's HTTP methods are inspected and the access restriction is enforced.
- **TLS inspection** — do not add `tls: skip` for ordinary HTTPS sources. Use it only when TLS
  inspection is incompatible with a required endpoint, and explain the reduced visibility and
  security tradeoff to the user.
- **`binaries`** — the standard node/python/curl set above covers WebFetch-style clients; reuse it
  as-is unless the user wants tighter restriction.

## 2. Tell the user to save the file — on the host

Instruct the user to save the YAML **on their host machine** (not in the sandbox) as
`<domain-name>.yaml`, named after the site it opens — e.g. `huggingface.yaml`, `arxiv.yaml`. Any
directory on the host works; if they keep several policies, one directory for all of them is
convenient.

## 3. Tell the user to apply it — from the host

The user runs this **from the host machine**. It applies the policy immediately to the running
sandbox — no sandbox rebuild needed:

```bash
nemoclaw <sbx-name> policy-add --from-file <domain-name>.yaml
```

Replace `<sbx-name>` with their sandbox name and `<domain-name>.yaml` with the path to the file
they just saved. If they keep multiple policy files in one directory, they can apply them all at
once:

```bash
nemoclaw <sbx-name> policy-add --from-dir <policy-dir>/ --yes
```

## 4. Verify

Once the user confirms they ran the command, retry the fetch that was blocked. If it still fails,
check that the exact failing hostname (watch for redirects and CDN subdomains) has its own
`endpoints` entry, update the YAML, and have the user re-apply.
