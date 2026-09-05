# Brev Deployment

Follow [Getting Started](getting-started.md) on the Brev VM. The VM needs
Docker, OpenShell, and the repository; it does not need a Python virtual
environment.

After `bash scripts/bring-up.sh`, add Brev HTTP endpoints for:

| Port | Service |
|---:|---|
| `8800` | FinGuard UI |
| `6006` | Phoenix |

Keep port `8780` private because it represents the host-only payment rail.

After a Brev reconnect or VM resume, run `bash scripts/bring-up.sh` again. The
command is idempotent and reuses a healthy sandbox. If Brev preserved the
sandbox record but OpenShell reports its phase as `Error`, use
`bash scripts/bring-up.sh --recover-error` to replace only that failed sandbox.
The same command replaces a `Ready` sandbox when the required Hermes/Relay
versions are absent or its native Relay configuration is missing or invalid.

If a public endpoint returns `503`, verify its service locally first with
`curl -fsS http://127.0.0.1:6006` or
`curl -fsS http://127.0.0.1:8800`. A successful local request means the Brev
HTTP endpoint for that port should be restarted or recreated; it does not
require rebuilding the sandbox.

SSH tunneling is an alternative to public HTTP endpoints:

```bash
ssh -F ~/.brev/ssh_config \
  -L 8800:localhost:8800 \
  -L 6006:localhost:6006 \
  payment-ops
```

Then open `http://127.0.0.1:8800` and `http://127.0.0.1:6006` locally.
