# External credentials

Credential lifetime depends on how the key was supplied, not on the stage using it.

| Source | Lifetime | Available to |
| --- | --- | --- |
| Key entered in Settings | Current browser tab's credential lease | Stages using the shared External Endpoint |
| Provider key in `api.json` | On the app host, across browser sessions | All stages using the selected provider and endpoint |
| Keyless local server | No credential needed | Stages using Local |

The launcher imports `api.json` into a private, owner-readable file under `$BAC_DATA_DIR/credentials`. Only provider names, URLs and key availability reach Settings. Model discovery checks the selected endpoint. Opening another provider’s configuration loads its catalog without switching the active connection until you connect. [Setup and legacy compatibility](docker-setup.md#provider-keys)

Each browser document has its own credential session. Authenticated activity renews a 90-second lease every 20 seconds. Teardown revokes the session; if that signal is lost, expiry prevents new calls and the five-second sweeper releases stored references. Another tab cannot reuse a session-only key by leaving its key field blank. Already submitted model calls can finish.

OpenClaw connects through a loopback proxy with a non-secret placeholder. The proxy adds the provider key, forwards supported API paths and streamed responses, and does not follow redirects or log credentials. File-based provider credentials survive browser refresh and preserving restarts; session-only credentials do not.

Startup removes legacy external keys from app-managed settings and OpenClaw configuration copies, and redacts discovered old key values in app-owned runtime logs/state. This does not revoke provider keys or erase copies outside the app. Internal gateway authentication tokens remain separate.

Scout and other standard Web research agents can use Parallel Search without an API key. Parallel receives the search objective and search terms and may retain or use them. Use only information you can share publicly. [Parallel legal and privacy information](https://parallel.ai/legal)
