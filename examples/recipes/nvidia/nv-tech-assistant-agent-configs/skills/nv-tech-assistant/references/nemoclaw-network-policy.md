# Writing and applying NemoClaw network grants

Use this when a source you need is blocked by the sandbox network policy (fetches fail or return
policy-block errors), or when the user asks to open access to a new site. The fix is a small
`grants` entry in the user's NemoClaw deployment YAML plus one `nemoclaw apply` run on the host.
Apply updates the running sandbox in place; it keeps its files, conversations, and agent.

**Important: you cannot apply the grant yourself.** You are running inside the sandbox and are
not allowed to change its network policy from within. Your job is to author the YAML and give the
user exact instructions; the user must edit their deployment file and run the command **on their
host machine**. Say this explicitly so the user doesn't wait for you to do it.

## 1. Write the grant

Start from `references/nemoclaw-policy-template.yaml` (annotated). Present the finished YAML to
the user in a fenced code block so they can copy it.

Structure, using arXiv as an example:

```yaml
arxiv:                           # grant name: unique, kebab-case, named after the site
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
- **`binaries`** — leave it out. NemoClaw then limits the grant to the agent's own executables.
- **Name** — a grant name must not repeat one already under `grants`. To widen an existing
  grant, add endpoints to it instead.

## 2. Tell the user where to put it — on the host

Instruct the user to open the deployment YAML they applied (`nemoclaw.yaml` in the example
directory) **on their host machine** and add the grant under
`spec.sandboxes.<sandbox>.network.grants`, beside the existing `nvidia`, `github`,
`huggingface`, and `arxiv` grants. Indentation must match those entries.

## 3. Tell the user to apply it — from the host

The user runs these **from the host machine**, in the directory that holds the deployment YAML
and its state directory, with `NVIDIA_INFERENCE_API_KEY` set as for the first apply:

```bash
nemoclaw plan nemoclaw.yaml
nemoclaw apply nemoclaw.yaml
```

The plan should show only the sandbox policy changing. Apply sends the new rules to the running
sandbox; a request in progress during the update can fail and need a retry.

## 4. Verify

Once the user confirms they ran the command, retry the fetch that was blocked. If it still fails,
check that the exact failing hostname (watch for redirects and CDN subdomains) has its own
`endpoints` entry, update the YAML, and have the user apply again.
