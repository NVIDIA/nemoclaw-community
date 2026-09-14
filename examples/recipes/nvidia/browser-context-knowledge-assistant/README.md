<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Ask NemoClaw

| Catalog field | Value |
| --- | --- |
| Description | Adds an authenticated Chrome side panel that sends an arbitrary user prompt, readable page text, and the rendered visible viewport to a NemoClaw agent running with Hermes. |
| Industry | ✨ Other |
| Requirements | NemoClaw with Hermes · x86-64 Linux and Docker · Chrome 116+ · inference provider API key · Brev or another Linux host |
| NemoClaw | Unpinned |
| Harness | Hermes Unpinned |
| OpenShell | Unpinned |

This NVIDIA-authored recipe adds a small browser interface to NemoClaw running
with Hermes. A user
opens a web page, selects the **Ask NemoClaw** extension, and asks a question.
Every message includes a fresh capture of the active page's readable text and
a bounded JPEG image of the currently visible viewport.
The NemoClaw agent keeps the conversation and decides which installed skills are relevant
to the user's prompt.

The extension does not modify the page. It does not contain a Hermes password,
an inference API key, or an OAuth token.

## Screenshot

![Ask NemoClaw explains a synthetic browser page using readable text and the visible viewport](assets/ask-nemoclaw-browser-context.png)

This reproducible fixture shows the current extension interface without using a
private endpoint, personal profile, credential, or retained production
conversation. The page and response are synthetic; the same extension code is
used for the side-panel rendering.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | NVIDIA Recipe |
| Contributor or provenance | NVIDIA-authored example for the public NemoClaw Community repository. |
| Use this when | A user wants to ask a NemoClaw agent about the page currently open in Chrome without copying the page text manually. |
| You will get | A Chrome side panel with retained, isolated Hermes conversations, current-page context on every message, and local NeMo Relay ATIF traces. |
| Runs on | A Linux host that can run NemoClaw and Docker. The tested deployment path uses the NemoClaw Brev launchable. |
| Requires | Chrome 116+, NemoClaw with Hermes, Docker, and an inference provider credential entered during NemoClaw onboarding. |
| Verified on | Static and local tests, plus a fresh NemoClaw Brev launchable using NemoClaw 0.0.123, OpenShell 0.0.106, and `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` on September 14, 2026. The live test covered gateway handoff, custom Hermes image creation, extension connection, multimodal and follow-up turns, conversation isolation, and visibility in Hermes Sessions. |
| Evidence level | local/static and live Brev deployment |
| Support and maturity | Educational example with best-effort community support. See the repository [support policy](../../../../SUPPORT.md). |
| External access, data, and actions | Sends the active page URL, title, readable page text, selected text, rendered visible viewport, and user prompt to the configured Hermes inference provider. The base recipe does not write to the page or call Google Drive. Any tool action still requires an installed Hermes tool, credentials, and an OpenShell policy that permits its exact destination. |
| Start here | [Launch the Brev environment](#start-here), then prepare the custom Hermes image and load the unpacked extension. |
| Confirm success | [Verification](#verification) |

## Architecture

![Ask NemoClaw architecture showing the Chrome permission boundary, NemoClaw runtime, Hermes plugin, OpenShell controls, inference provider, optional skills, and local traces](assets/ask-nemoclaw-architecture.png)

Chrome grants temporary access to the active tab after the user selects the
extension. Ask NemoClaw sends the prompt and bounded browser context to one
user-configured Hermes origin. The plugin maps each browser conversation to a
separate non-PTY Hermes session. Hermes selects installed skills and tools,
OpenShell applies runtime controls, and NeMo Relay records local ATIF traces.
The session is stored in Hermes's normal profile-backed session database, so it
also appears in the Hermes dashboard without allocating a terminal or PTY.

The Chrome extension can reach only an origin granted through Chrome host
permissions. The Brev quick start uses an authenticated Brev CLI port forward
to a loopback-only Hermes listener. A shared deployment instead requires an
authenticated HTTPS ingress that supports API clients. The extension derives
the service endpoint from the dashboard URL. It checks the standard Hermes path
`/api/plugins/ask-nemoclaw` and the Brev adapter path `/ask-nemoclaw`.

The community extension contains no initial deployment hostname. On first use,
the side panel opens Settings and asks for one NemoClaw dashboard URL. Chrome
then asks the user to grant access to that exact origin. The selected URL is
retained in extension-local settings and can be changed later with the gear
control without reinstalling the extension. Service discovery remains
restricted to the selected origin. When a portable installation changes
origins, it removes the previously granted optional origin permission.
Upgrading from an older preconfigured development build discards that build's
legacy stored URL once; URLs explicitly saved through the portable Settings
screen persist across later extension reloads and upgrades.

The extension also requests Chrome's `cookies` permission. Chrome combines
this permission with the exact host permission granted by the user, so Ask
NemoClaw can read Hermes session cookies only for the configured deployment.
It converts the access token to Hermes's supported bearer authentication and
uses `/auth/native/refresh` when needed. Tokens copied by the extension are
kept only in Chrome's memory-backed `storage.session` and are cleared when
Chrome exits. No authentication value is written to extension-local or
synchronized storage.

For the loopback Brev flow, Hermes instead embeds a random, short-lived session
token in the dashboard page. The extension reads that token from the forwarded
local dashboard and sends it only to the same origin in the
`X-Hermes-Session-Token` header. The token is held only in extension memory;
the user does not enter or manage it.

The plugin accepts the pinned public extension identifier generated by the
manifest's public key. This value identifies the extension origin; it is not a
credential. An enterprise distribution can set
`HERMES_ASK_NEMOCLAW_EXTENSION_ID` to its centrally published extension ID.

## Security Boundary

Page text and rendered pixels are untrusted input. The plugin wraps them
separately from the signed-in user's prompt and tells Hermes not to treat page
content as instructions. This
reduces prompt-injection risk, but it does not make untrusted content safe by
itself. OpenShell remains the enforcement boundary for network access and
external tools.

The base recipe:

- requires an authenticated Hermes session for shared HTTPS deployments;
- permits a single local development identity only when the prepared image
  explicitly enables loopback mode through its environment or a root-owned,
  read-only marker and the request host is loopback;
- verifies the browser origin;
- strips URL credentials and fragments, preserves ordinary query parameters
  needed to identify the page, and removes credential-like query parameters;
- limits request and response sizes;
- accepts only a bounded, browser-generated JPEG viewport image;
- permits viewport-only context when a canvas-based or otherwise rendered page
  does not expose readable DOM text;
- attaches that image to the same Hermes session that receives the prompt;
- removes the temporary gateway image after the turn completes;
- requires an idempotency key for each message;
- isolates conversations by the authenticated Hermes user;
- creates a separate Hermes session for every new side-panel conversation;
- reuses that session only for later messages in the same conversation;
- lists completed extension conversations in the owning Hermes dashboard profile;
- never allocates a terminal or PTY; and
- performs no page writes and adds no external egress policy.

NeMo Relay runs inside the Hermes process. It writes Agent Trajectory
Interchange Format (ATIF) files to
`/sandbox/.hermes-data/nemo-relay/atif`. These files can contain the user's
prompt, captured page context, model output, and tool events. Treat them as
sensitive data. The base recipe does not send traces to an OpenTelemetry or
other external collector.

The text capture uses `document.body.innerText`. The viewport capture adds the
currently rendered charts, images, canvas content, layout, and formatting. It
does not capture content above or below the visible viewport, other tabs, or
Chrome's toolbar. Chrome internal pages are rejected. A page without readable
DOM text can still be submitted when the extension captures a valid viewport
image.

The inference path must provide image understanding. The tested NemoClaw and
OpenShell configuration enforces one model for every inference request in the
workspace. That route overrides a different model selected through Hermes's
auxiliary-vision setting. Select a multimodal primary model during onboarding;
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` is the model used by this
recipe's visual-context test. A text-only primary route cannot process the
viewport image. Confirm that the configured provider is approved to receive
the rendered page image and readable page text.

## Installation Approaches

The supported and reproducible path in this recipe installs the Hermes plugin
and local NeMo Relay configuration while building the sandbox image. This
ensures plugin enablement, the Brev loopback trust marker, Python dependency
compatibility, and local trace configuration are present when the sandbox
starts and when it is rebuilt.

A shorter development path based on `hermes plugins install` is being
evaluated, but is not yet a supported procedure in this recipe. Before it can
replace image-time installation for evaluation, the standalone plugin must be
verified for:

- installation from an immutable Git commit and this monorepo subdirectory;
- explicit Hermes plugin enablement and dashboard API discovery;
- dashboard restart and host reboot persistence;
- the minimum OpenShell policy required to retrieve the Git source;
- authenticated HTTPS ingress behavior without weakening the loopback trust
  check; and
- NemoClaw sandbox rebuild, backup, and restore behavior.

The intended future quick start is: launch and onboard NemoClaw with Hermes,
install and enable the pinned Ask NemoClaw plugin, forward the Hermes dashboard
port for local evaluation, and load the Chrome extension. Keep the image-time
path for a pinned, reproducible deployment.

## Start Here

### 1. Create a Brev host

Open the [NemoClaw Brev launchable](https://brev.nvidia.com/launchable/deploy/now?launchableID=env-3Azt0aYgVNFEuz7opyx3gscmowS)
and create one instance. At the time this recipe was prepared, the launchable
selected a CPU-only `n2d-standard-4` instance with 4 vCPUs, 16 GiB RAM, and
256 GB storage.

Do not run the launchable's NemoClaw onboarding flow or create a sandbox yet.
The following sections update the host, prepare the custom Hermes image with
the Ask NemoClaw plugin, and then run the recipe's onboarding procedure in
place of the launchable's standard onboarding steps.

Stop or delete the instance when you finish. A stopped instance can continue
to incur storage charges.

### 2. Prepare the fresh Brev host

Connect to the Brev instance. Do not use the launchable's web onboarding page
yet. Confirm that the host contains no sandbox:

```bash
openshell sandbox list
```

Some launchable revisions use Docker's containerd snapshotter, which cannot
provide the nested overlay mounts required by the OpenShell sandbox. If
`docker info --format '{{json .DriverStatus}}'` contains
`io.containerd.snapshotter.v1`, switch this fresh host to classic overlay2:

```bash
printf '%s\n' \
  '{' \
  '  "features": {' \
  '    "containerd-snapshotter": false' \
  '  }' \
  '}' \
  | sudo tee /etc/docker/daemon.json >/dev/null
sudo systemctl restart docker
docker info --format 'Driver={{.Driver}} Status={{json .DriverStatus}}'
```

The result must report `Driver=overlay2`.

The launchable installation is a source checkout, so `nemoclaw update --yes`
reports the available release but intentionally does not replace it. Run the
maintained installer from `/tmp` without selecting or onboarding against the
launchable's older OpenShell gateway:

```bash
cd /tmp
curl -fsSL https://www.nvidia.com/nemoclaw.sh \
  | env -u NVIDIA_INFERENCE_API_KEY -u NVIDIA_API_KEY \
      NEMOCLAW_AGENT=hermes \
      bash
```

Review and explicitly accept the third-party software terms. Do not automate
that acceptance for another user. The installer may then attempt its standard
onboarding flow. Do not enter an inference credential or create a sandbox yet;
cancel at the first onboarding prompt. On launchable revisions with the legacy
gateway declaration, onboarding can instead stop by itself with
`Invalid gateway management declaration`. That message does not mean the CLI
upgrade failed. Continue with the gateway handoff below. The example must
prepare the Hermes image before onboarding creates the only sandbox.

Refresh the shell command path after the installer. The maintained installation
is user-local and must take precedence over older launchable binaries:

```bash
source "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"
command -v nemoclaw nemohermes openshell
nemoclaw --version
openshell --version
```

#### Hand the empty gateway to the updated installation

The tested launchable runs an older, externally supervised OpenShell gateway.
It can answer health requests, but it does not implement the complete inference
configuration contract required by the updated NemoClaw client. The resulting
onboarding failure is `Operation is not implemented or not supported`, even
after model validation succeeds.

Clone this repository, then run the guarded handoff and compatibility check:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/recipes/nvidia/browser-context-knowledge-assistant
bash scripts/prepare-brev-gateway.sh
bash scripts/check-brev-host.sh
```

The handoff first proves that the old gateway contains no sandboxes. It then
stops and disables only `openshell-gateway.service`, removes the stale local
registration, and leaves the launchable's gateway data intact. The onboarding
script selects an explicit `nemoclaw-managed` declaration and opts into
NemoClaw's authenticated gateway compatibility container. This mode is needed
because the tested launchable uses Ubuntu 22.04/glibc 2.35 while the current
native OpenShell gateway requires a newer host ABI. The script also clears the
retired gateway's exported state and TLS paths for the onboarding child process
so the managed gateway creates user-owned state under the normal NemoClaw
directory.

Do not copy newer OpenShell binaries into `/usr/local/bin`. Replacing individual
binaries can leave the gateway and sandbox driver incompatible with each other.

### 3. Build the custom Hermes sandbox

Start from a normal NemoClaw installation configured to use Hermes. The
supported NemoClaw path for Hermes runtime additions is a custom sandbox image.
The setup script finds the source checkout used by the installed `nemohermes`
installation, copies the `ask-nemoclaw` Hermes plugin into Hermes's shared,
root-owned plugin directory, adds the local Relay configuration to that
checkout, and enables both additions through
NemoClaw's managed Hermes policy. The preparation also adds the top-level
`plugins` configuration to the reviewed dashboard-mirroring keys so Hermes's
isolated dashboard process authorizes the same plugin API as the main agent
process. It installs the checksum-pinned NeMo Relay
`0.7.2` x86-64 wheel and verifies the complete Python environment with
`uv pip check`; this version satisfies the Hermes dependency ranges tested by
the example. It also preserves the built-in `nemoclaw` plugin and the rest of
the standard image.
The script creates the one sandbox required by this example. Do not create a
standard Hermes sandbox first: every sandbox registered to the same OpenShell
gateway shares one forced inference route, and a second sandbox recorded with
a different model blocks a supported model switch.

The script passes `--from` with the exact repository-owned Hermes Dockerfile.
NemoClaw recognizes that trusted path, stages the complete source repository,
and builds the prepared image with local BuildKit. Omitting `--from` selects
NVIDIA's stock managed Hermes image, which does not contain this recipe's
backend plugin or loopback marker.

```bash
bash scripts/onboard.sh --fresh
```

Onboarding asks you to select an inference provider and enter its credential.
Use the normal NemoClaw credential prompt. Do not place the credential in this
repository or in the Chrome extension. To exercise viewport understanding,
select `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` as the primary model.
Selecting a text-only primary model and then choosing Omni only in Hermes's
auxiliary-vision dialog does not change OpenShell's enforced route.

Provider and model environment variables supply onboarding defaults. In
interactive mode, NemoHermes still displays those choices for confirmation;
this does not mean that the variables were ignored.

To discard this example sandbox and build it again from a clean state, use the
explicit recreation flag:

```bash
bash scripts/onboard.sh --recreate-sandbox
```

This removes the existing example sandbox, including its conversations and
workspace state, clears its lifecycle registration, and starts a fresh
onboarding session. It also releases only the verified OpenShell service
forwards belonging to that sandbox. Normal runs without
`--recreate-sandbox` remain non-destructive.

The default sandbox name is `ask-nemoclaw`. To use another name of 19 or fewer
characters:

```bash
NEMOCLAW_SANDBOX_NAME=my-browser-agent bash scripts/onboard.sh
```

If this recipe's image build is interrupted, resume it with the same trusted
Dockerfile selection:

```bash
bash scripts/onboard.sh --resume
```

Confirm readiness:

```bash
nemohermes ask-nemoclaw status
nemohermes ask-nemoclaw dashboard-url --quiet
```

Do not configure Hermes dashboard authentication for the Brev loopback quick
start. The sandbox image contains a root-owned, read-only marker that permits
one development identity only when Hermes sees a loopback hostname. External
requests without a Hermes session remain unauthorized. The authenticated Brev
CLI tunnel is the access boundary for this single-user development mode.

The included `configure_dashboard_auth.py` helper is for a later shared HTTPS
deployment. It is not part of the Brev quick start.

### 4. Forward Hermes to the workstation

Run the following on the workstation where Chrome is installed:

```bash
brev port-forward <brev-instance-name> -p 18789:18789
```

If NemoClaw selected a different dashboard port, use that number on both sides.
Keep this terminal running while you use the extension.

Enter `http://127.0.0.1:18789` in the extension settings. No Hermes login is
required in this loopback development mode. The extension should immediately
create its first conversation. The port-forward command must continue running.
Multimodal reasoning over a large page can take several minutes; the side panel
continues polling while Hermes works, and the backend interrupts a request that
does not finish within five minutes.

Before opening Chrome, verify that both the tunnel and login-free backend mode
are active:

```bash
bash scripts/check-connection.sh http://127.0.0.1:18789
```

The final two lines must report HTTP 200 for the Ask NemoClaw API and
`Loopback development connection is ready`. If the check reports that Hermes
requires authentication, the sandbox was configured for a shared deployment
or was built before the loopback marker was added. Do not treat that as a
port-forward failure; recreate the development sandbox from the current recipe
if its existing conversations do not need to be retained.

If local port `18789` is already occupied, map another local port to the remote
dashboard port, for example:

```bash
brev port-forward <brev-instance-name> -p 18790:18789
```

Then configure the extension with `http://127.0.0.1:18790`.

Do not enter a Brev Secure Link such as `https://<port>-<id>.gobrev.dev` in the
extension. Brev Secure Links protect web pages with redirect-based browser
authentication. Cross-origin extension API requests cannot complete that
redirect flow. [NVIDIA's Brev connectivity documentation](https://docs.nvidia.com/brev/cli/connectivity)
recommends port forwarding for direct API clients. The extension detects these
hostnames and explains this requirement rather than repeatedly requesting
Hermes sign-in.

For a shared or centrally managed deployment, expose Hermes through an ordinary
HTTPS ingress that permits authenticated API requests from the extension and
retain Hermes authentication. The included Nginx template is an integration
reference for such an ingress; a Brev Secure Link is not that API ingress.

### 5. Build and load the Chrome extension

On the workstation, clone the community repository if it is not already
available, then enter the example directory:

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/recipes/nvidia/browser-context-knowledge-assistant
```

Build the portable extension:

```bash
bash scripts/build-extension.sh
```

Then:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Select the printed `build/extension` directory.
5. Pin **Ask NemoClaw** to the Chrome toolbar.
6. Open the side panel, enter `http://127.0.0.1:18789` in Settings, and approve
   Chrome's request for that exact origin.

Install this portable build once. Change deployments later from the Settings
gear; rebuilding or reinstalling is not required.

An administrator can optionally produce a preconfigured managed build with one
initial HTTPS origin:

```bash
bash scripts/build-extension.sh https://hermes.example.com
```

The preconfigured form includes the exact initial host permission. Both forms
contain no credential. Enter only the NemoClaw dashboard URL; the extension
infers the plugin endpoint, including the Brev adapter path.

## Use the Assistant

1. Open a normal HTTP or HTTPS page.
2. Select the **Ask NemoClaw** toolbar icon. This click grants temporary access
   to that tab and opens the side panel.
3. Enter any prompt and select **Send**.

The connection indicator reports whether the configured Hermes API is signed
in, requires authentication, or is unavailable. The settings gear changes the
NemoClaw URL and requests the required Chrome host permission.
**Open NemoClaw** opens the configured dashboard URL so the user can complete
normal authentication.
**Check current connection** is available inside settings for a manual read-only
retry after sign-in or service recovery.
Authentication remains at the configured protected dashboard origin; the
extension never stores a username, password, API key, token, or cookie in
persistent storage. After a normal sign-in, the dashboard tab can be closed.
The extension reads only the configured origin's Hermes session cookies and
keeps any rotated bearer session only in Chrome's memory-backed session
storage. **Disconnect** removes this extension session, its saved deployment
URL, and the exact-origin permission. It does not sign the dashboard out.

Every message recaptures the available page text and visible viewport. A page
that exposes no readable DOM text can still be sent using its viewport image.
The NemoClaw agent chooses relevant installed skills from the user's prompt.
The extension does not map domains or URL patterns to particular skills.

For example, a Google Docs URL remains ordinary browser context. If the Hermes
deployment has a Google Docs skill or tool, its authorization is complete, and
OpenShell permits the required destinations, the agent can select that
capability when the user's request requires it. Otherwise, the agent works only
from the readable text and viewport supplied by the extension.

After changing browser tabs, select the toolbar icon on the new tab before
selecting **Refresh**. This preserves the extension's narrow `activeTab`
permission instead of granting persistent access to every tab.

## Verification

Run the local test suite:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh
```

An operator can also check a route without sending a password or session
cookie:

```bash
bash scripts/check-connection.sh https://hermes.example.com
```

HTTP 302, 401, or 403 can be the expected authentication boundary. The Chrome
side panel performs the final check with the user's normal Hermes session. For
an HTTP loopback origin, the script is stricter: Hermes must report that
authentication is disabled, provide its ephemeral dashboard session token, and
accept that token on the Ask NemoClaw API. The checker never prints or stores
the token.

Expected evidence:

- JavaScript syntax and side-panel response parsing pass;
- the Python tests pass authentication, origin, input, conversation isolation,
  idempotency, bounded-image validation, same-session image attachment,
  cancellation, result parsing, and non-PTY checks; and
- extension builds succeed for both HTTPS and optional HTTP loopback origins;
- the prepared image layer validates the Hermes-bundled NeMo Relay package,
  enables `observability/nemo_relay`, and configures only local ATIF output.

For a live verification:

1. Start the Brev port forward and configure the extension with its localhost
   URL. Confirm that the extension creates a conversation without a Hermes
   login prompt.
2. Open the Hermes dashboard through the same localhost URL and confirm
   ordinary dashboard chat still works.
3. Open a public page with readable text and a distinctive visible diagram or
   color, then select the extension icon.
4. Ask for a short summary and a description of the visible diagram. Confirm
   the answer uses both readable text and rendered pixels from the page.
5. Send a follow-up question and confirm it retains the conversation.
6. Select **New**, ask another question, and confirm it does not inherit the
   earlier conversation.
7. Open Hermes **Sessions** and confirm both extension conversations appear
   under the active profile with their browser conversation titles.
8. Change tabs, select the toolbar icon on the new tab, select **Refresh**, and
   confirm a new conversation starts with the new page context.
9. Inspect the OpenShell policy and confirm this recipe added no external host.
10. In the sandbox, list `/sandbox/.hermes-data/nemo-relay/atif` and confirm a
   new JSON file was created for the review session. Inspect only its schema or
   field names if the page content is sensitive.

## Files

| Path | Purpose |
| --- | --- |
| `extension/` | Manifest V3 Chrome side-panel source. |
| `hermes-plugin/` | Authenticated Hermes REST adapter backed by non-PTY JSON-RPC sessions. |
| `relay/plugins.toml` | Local-only NeMo Relay ATIF configuration with provider-placeholder redaction. |
| `scripts/prepare-hermes-image.py` | Adds the plugin, Relay configuration, and managed enablement to the complete Hermes image source. |
| `scripts/check-brev-host.sh` | Performs read-only launchable compatibility checks before onboarding. |
| `scripts/prepare-brev-gateway.sh` | Proves the legacy Brev gateway is empty and hands lifecycle control to the current NemoClaw installation. |
| `scripts/onboard.sh` | Builds and onboards the custom Hermes sandbox. |
| `scripts/build-extension.sh` | Produces a portable unpacked extension, or an optional preconfigured build when passed one exact origin. |
| `deploy/nginx/ask-nemoclaw-server.conf` | Reference reverse proxy for an HTTPS ingress that supports extension API requests. |
| `scripts/check-connection.sh` | Checks the dashboard and plugin routes without user-managed credentials; loopback checks use Hermes's in-memory ephemeral dashboard token. |
| `scripts/verify.sh` | Runs static and local tests. |
| `tests/` | Python API and JavaScript rendering tests with synthetic data. |

## Limitations

- Viewport capture includes only the currently visible page area. It does not
  capture off-screen content or the full browser accessibility tree.
- Chrome's `activeTab` permission requires a toolbar click on each new tab.
- The base recipe does not install or configure Google Workspace access. A
  Google Docs skill or tool requires separate installation, authorization, and
  OpenShell policy configuration.
- The prompt/data separation is a defense-in-depth control, not a complete
  solution to prompt injection.
- Local ATIF traces contain sensitive conversation and page context until the
  operator removes them. The example does not include retention or automatic
  deletion policy.
- Central Chrome distribution requires normal Chrome Enterprise packaging,
  signing, and policy management outside this repository.

## Cleanup

Stop the sandbox without deleting its state:

```bash
nemohermes ask-nemoclaw stop
```

To remove the sandbox and its workspace, inspect the name first and then run:

```bash
nemohermes ask-nemoclaw destroy
```

The destroy command is destructive and asks for confirmation. Also stop or
delete the Brev instance separately when you no longer need it.
