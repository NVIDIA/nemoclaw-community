#!/usr/bin/env bash
# Configure an existing NemoClaw/OpenClaw sandbox for the Omni vision sub-agent demo.
#
# Usage:
#   export NVIDIA_API_KEY=nvapi-...
#   SANDBOX=hclaw bash scripts/apply-omni-subagent.sh
#
# Optional:
#   SEED_DEMO_IDENTITY=1  Move BOOTSTRAP.md aside and write minimal demo identity files.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
if [[ -f "$HERE/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HERE/.env"
    set +a
fi

SANDBOX="${SANDBOX:-hclaw}"
DOCKER_CTR="${DOCKER_CTR:-openshell-cluster-nemoclaw}"
OMNI_MODEL="${OMNI_MODEL:-nvidia/nemotron-3-nano-omni-30b-a3b-reasoning}"
SUPER_MODEL="${SUPER_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
NEMO_FLOW_PROJECT_NAME="${NEMO_FLOW_PROJECT_NAME:-openclaw-omni-demo}"
BACKUP_DIR="${BACKUP_DIR:-$(mktemp -d "/tmp/${SANDBOX}-openclaw-omni.XXXXXX")}"
DATA_WORKSPACE="/sandbox/.openclaw-data/workspace"
DATA_AGENT_DIR="/sandbox/.openclaw-data/agents/vision-operator"
ACTIVE_AGENT_DIR="/sandbox/.openclaw/agents/vision-operator"
PLUGIN_RUNTIME_DEPS="/sandbox/.openclaw-data/plugin-runtime-deps"
ACTIVE_PLUGIN_RUNTIME_DEPS="/sandbox/.openclaw/plugin-runtime-deps"
DATA_TMP="/sandbox/.openclaw-data/tmp"

log() { printf '→ %s\n' "$*"; }
need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing required command: $1" >&2
        exit 1
    fi
}

need docker
need openshell
need python3

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
    echo "NVIDIA_API_KEY is required. Export an nvapi key with Omni access before running." >&2
    exit 2
fi
if [[ "$NVIDIA_API_KEY" != nvapi-* ]]; then
    echo "NVIDIA_API_KEY does not look like an nvapi key." >&2
    exit 2
fi
chmod 700 "$BACKUP_DIR"

kexec() {
    docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- "$@"
}

log "sandbox: $SANDBOX"
log "backup dir: $BACKUP_DIR"
openshell sandbox get "$SANDBOX" >/dev/null
if [[ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ]]; then
    log "Phoenix project: $NEMO_FLOW_PROJECT_NAME"
    log "OpenClaw traces require a NemoFlow-enabled OpenClaw runtime; see docs/telemetry.md"
fi

# 1. Patch policy so the OpenClaw gateway/node process can call NVIDIA directly.
log "backing up and patching policy"
openshell policy get "$SANDBOX" --full > "$BACKUP_DIR/policy-full-before.txt"
awk '/^---$/{seen=1; next} seen' "$BACKUP_DIR/policy-full-before.txt" > "$BACKUP_DIR/policy-before.yaml"
python3 - "$BACKUP_DIR/policy-before.yaml" "$BACKUP_DIR/policy-updated.yaml" <<'PY'
from pathlib import Path
import sys
src, dst = map(Path, sys.argv[1:3])
lines = src.read_text().splitlines()
start = next((i for i, line in enumerate(lines) if line == "  nvidia:"), None)
if start is None:
    raise SystemExit("could not find network_policies.nvidia block")
end = len(lines)
for i in range(start + 1, len(lines)):
    line = lines[i]
    if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
        end = i
        break
block = lines[start:end]
if any("/usr/local/bin/node" in line for line in block):
    dst.write_text("\n".join(lines) + "\n")
    raise SystemExit(0)
insert_at = None
for offset, line in enumerate(block):
    if line.strip() == "- path: /usr/local/bin/openclaw":
        insert_at = start + offset + 1
if insert_at is None:
    for offset, line in enumerate(block):
        if line.strip() == "binaries:":
            insert_at = start + offset + 1
            break
if insert_at is None:
    raise SystemExit("could not find nvidia.binaries list")
lines.insert(insert_at, "    - path: /usr/local/bin/node")
dst.write_text("\n".join(lines) + "\n")
PY
if ! cmp -s "$BACKUP_DIR/policy-before.yaml" "$BACKUP_DIR/policy-updated.yaml"; then
    openshell policy set --policy "$BACKUP_DIR/policy-updated.yaml" "$SANDBOX"
else
    log "policy already includes /usr/local/bin/node"
fi

# 2. Patch openclaw.json.
log "backing up and patching openclaw.json"
kexec cat /sandbox/.openclaw/openclaw.json > "$BACKUP_DIR/openclaw-before.json"
chmod 600 "$BACKUP_DIR/openclaw-before.json"
python3 - "$BACKUP_DIR/openclaw-before.json" "$BACKUP_DIR/openclaw-updated.json" "$OMNI_MODEL" "$SUPER_MODEL" <<'PY'
import json
import sys
src, dst, omni_model, super_model = sys.argv[1:5]
with open(src) as f:
    config = json.load(f)
models = config.setdefault("models", {})
models.setdefault("mode", "merge")
providers = models.setdefault("providers", {})
providers["nvidia-omni"] = {
    "baseUrl": "https://integrate.api.nvidia.com/v1",
    # The helper replaces this placeholder while streaming the config into the
    # sandbox. Keeping the placeholder in the host-side backup avoids writing
    # the NVIDIA key to /tmp on the host.
    "apiKey": "__NVIDIA_API_KEY_FROM_ENV__",
    "api": "openai-completions",
    "models": [{
        "id": omni_model,
        "name": f"nvidia-omni/{omni_model}",
        "reasoning": True,
        "input": ["text", "image"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 131072,
        "maxTokens": 16384,
    }],
}
agents = config.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
defaults["model"] = {"primary": f"inference/{super_model}"}
defaults["timeoutSeconds"] = max(int(defaults.get("timeoutSeconds", 300) or 300), 300)
defaults["subagents"] = {"maxConcurrent": 4, "maxSpawnDepth": 1}
agents["list"] = [
    {
        "id": "main",
        "model": {"primary": f"inference/{super_model}"},
        "subagents": {"allowAgents": ["vision-operator"]},
        "tools": {"profile": "full"},
    },
    {
        "id": "vision-operator",
        "workspace": "/sandbox/.openclaw-data/workspace",
        "model": {"primary": f"nvidia-omni/{omni_model}"},
        "tools": {"profile": "full", "deny": ["message", "sessions_spawn"]},
    },
]
plugins = config.setdefault("plugins", {})
plugins["enabled"] = False
plugins.setdefault("slots", {})["memory"] = "none"
plugin_entries = plugins.setdefault("entries", {})
for plugin_id in [
    # These enabled-by-default extensions are unrelated to the Omni sub-agent
    # demo. Disabling them keeps first-run CLI checks from staging bundled npm
    # deps for browsers, speech/media integrations, and unused model providers.
    "acpx",
    "alibaba",
    "amazon-bedrock",
    "amazon-bedrock-mantle",
    "anthropic",
    "anthropic-vertex",
    "arcee",
    "bonjour",
    "browser",
    "byteplus",
    "chutes",
    "cloudflare-ai-gateway",
    "codex",
    "comfy",
    "copilot-proxy",
    "deepgram",
    "deepseek",
    "device-pair",
    "document-extract",
    "elevenlabs",
    "fal",
    "fireworks",
    "github-copilot",
    "google",
    "groq",
    "huggingface",
    "kilocode",
    "kimi",
    "litellm",
    "lmstudio",
    "microsoft",
    "microsoft-foundry",
    "memory-core",
    "minimax",
    "mistral",
    "moonshot",
    "ollama",
    "openai",
    "opencode",
    "opencode-go",
    "openrouter",
    "nvidia",
    "phone-control",
    "qianfan",
    "qqbot",
    "qwen",
    "runway",
    "sglang",
    "stepfun",
    "synthetic",
    "talk-voice",
    "tencent",
    "together",
    "venice",
    "vercel-ai-gateway",
    "vllm",
    "volcengine",
    "voyage",
    "vydra",
    "web-readability",
    "xai",
    "xiaomi",
    "zai",
]:
    plugin_entries.setdefault(plugin_id, {})["enabled"] = False
with open(dst, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
PY
chmod 600 "$BACKUP_DIR/openclaw-updated.json"
kexec chmod 644 /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash
python3 - "$BACKUP_DIR/openclaw-updated.json" <<'PY' | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw/openclaw.json >/dev/null
import json
import os
import sys
with open(sys.argv[1]) as f:
    config = json.load(f)
config["models"]["providers"]["nvidia-omni"]["apiKey"] = os.environ["NVIDIA_API_KEY"]
json.dump(config, sys.stdout, indent=2)
sys.stdout.write("\n")
PY
kexec /bin/bash -c 'cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash && chmod 444 openclaw.json .config-hash'

# 3. Provision the shared workspace and both observed agent data paths. Current
# OpenClaw reports ~/.openclaw/agents/vision-operator/agent as the active agent
# dir, while older cookbook notes used ~/.openclaw-data/agents.
log "ensuring demo workspace and vision-operator agent dirs"
kexec bash -c "mkdir -p \
  '$DATA_WORKSPACE' \
  '$DATA_AGENT_DIR/agent' \
  '$DATA_AGENT_DIR/sessions' \
  '$ACTIVE_AGENT_DIR/agent' \
  '$ACTIVE_AGENT_DIR/sessions' \
  '$PLUGIN_RUNTIME_DEPS' \
  '$DATA_TMP' && \
  chown -R sandbox:sandbox \
  '$DATA_WORKSPACE' \
  '$DATA_AGENT_DIR' \
  '$ACTIVE_AGENT_DIR' \
  '$PLUGIN_RUNTIME_DEPS' \
  '$DATA_TMP' && \
  rm -rf '$ACTIVE_PLUGIN_RUNTIME_DEPS' && \
  ln -sfn '$PLUGIN_RUNTIME_DEPS' '$ACTIVE_PLUGIN_RUNTIME_DEPS' && \
  find '$PLUGIN_RUNTIME_DEPS' -mindepth 2 -maxdepth 2 -type d -name .openclaw-runtime-deps.lock -prune -exec rm -rf {} +"

# OpenClaw 2026.4 can scan bundled provider plugins during gateway/agent
# startup before the demo's disabled plugin config has short-circuited every
# path. Seed dependency sentinels in the external runtime-deps cache so those
# scans do not spend minutes in npm for extensions this demo never activates.
log "seeding disabled bundled plugin runtime dependency sentinels"
kexec bash -lc "PLUGIN_RUNTIME_DEPS='$PLUGIN_RUNTIME_DEPS' python3 - <<'PY'
import hashlib
import json
import os
import re
from pathlib import Path

package_root = Path('/usr/local/lib/node_modules/openclaw').resolve()
extensions_dir = package_root / 'dist' / 'extensions'
if not extensions_dir.exists():
    raise SystemExit(0)

version = 'unknown'
try:
    version = json.loads((package_root / 'package.json').read_text()).get('version') or version
except OSError:
    pass
package_key = 'openclaw-{}-{}'.format(
    re.sub(r'[^A-Za-z0-9._-]+', '-', version).strip('-') or 'unknown',
    hashlib.sha256(str(package_root).encode()).hexdigest()[:12],
)
install_root = Path(os.environ['PLUGIN_RUNTIME_DEPS']) / package_key
node_modules = install_root / 'node_modules'
node_modules.mkdir(parents=True, exist_ok=True)

def normalized_version(spec):
    spec = str(spec).strip()
    if not spec or spec.lower().startswith('workspace:'):
        return None
    if spec[0] in '^~':
        spec = spec[1:]
    return spec if re.match(r'^[0-9]+\\.[0-9]+\\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$', spec) else None

deps = {}
for package_json in extensions_dir.glob('*/package.json'):
    try:
        data = json.loads(package_json.read_text())
    except (OSError, json.JSONDecodeError):
        continue
    for name, raw_spec in (data.get('dependencies') or {}).items():
        version = normalized_version(raw_spec)
        if version:
            deps[name] = version

index_js = '''export default {};
export class BedrockClient { async send() { return {}; } }
export class BedrockRuntimeClient { async send() { return {}; } }
export class GetInferenceProfileCommand { constructor(input) { this.input = input; } }
export class ListFoundationModelsCommand { constructor(input) { this.input = input; } }
export class ListInferenceProfilesCommand { constructor(input) { this.input = input; } }
'''

for name, version in sorted(deps.items()):
    package_dir = node_modules.joinpath(*name.split('/'))
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / 'package.json').write_text(json.dumps({
        'name': name,
        'version': version,
        'type': 'module',
        'exports': './index.js',
    }, indent=2) + '\\n')
    (package_dir / 'index.js').write_text(index_js)

(install_root / '.openclaw-runtime-deps.json').write_text(json.dumps({
    'specs': sorted(f'{name}@{version}' for name, version in deps.items())
}, indent=2) + '\\n')
print(f'seeded {len(deps)} bundled runtime dependency sentinels in {install_root}')
PY
chown -R sandbox:sandbox '$PLUGIN_RUNTIME_DEPS'"

# 4. Write the per-agent auth profile in the OpenClaw 2026.4 auth-profile format.
log "writing vision-operator auth profile"
auth_profile=$(python3 - <<'PY'
import json
import os
key = os.environ["NVIDIA_API_KEY"]
print(json.dumps({
    "version": 1,
    "profiles": {
        "nvidia-omni:default": {
            "type": "api_key",
            "provider": "nvidia-omni",
            "key": key,
            "displayName": "NVIDIA Omni",
        }
    },
    "order": {"nvidia-omni": ["nvidia-omni:default"]},
}, indent=2))
PY
)
printf '%s\n' "$auth_profile" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee "$DATA_AGENT_DIR/agent/auth-profiles.json" >/dev/null
printf '%s\n' "$auth_profile" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee "$ACTIVE_AGENT_DIR/agent/auth-profiles.json" >/dev/null
kexec chmod 600 "$DATA_AGENT_DIR/agent/auth-profiles.json" "$ACTIVE_AGENT_DIR/agent/auth-profiles.json"
kexec chown sandbox:sandbox "$DATA_AGENT_DIR/agent/auth-profiles.json" "$ACTIVE_AGENT_DIR/agent/auth-profiles.json"

# 5. Copy demo instructions into the shared workspace.
log "copying AGENTS.md and TOOLS.md into workspace"
cat "$HERE/agents/openclaw/workspace/AGENTS.md" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee "$DATA_WORKSPACE/AGENTS.md" >/dev/null
cat "$HERE/agents/openclaw/workspace/TOOLS.md" | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee "$DATA_WORKSPACE/TOOLS.md" >/dev/null

# 6. Optional: seed identity so scripted smoke tests do not get intercepted by BOOTSTRAP.md.
if [[ "${SEED_DEMO_IDENTITY:-0}" == "1" ]]; then
    log "seeding demo identity and moving BOOTSTRAP.md aside"
    kexec bash -c "cd '$DATA_WORKSPACE' && tar cf /tmp/openclaw-demo-identity-before.tar BOOTSTRAP.md IDENTITY.md USER.md SOUL.md 2>/dev/null || true"
    kexec cat /tmp/openclaw-demo-identity-before.tar > "$BACKUP_DIR/openclaw-demo-identity-before.tar" 2>/dev/null || true
    kexec bash -c "cd '$DATA_WORKSPACE' && [ ! -f BOOTSTRAP.md ] || mv BOOTSTRAP.md BOOTSTRAP.md.disabled-for-omni-demo"
    cat <<'IDENTITY' | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee "$DATA_WORKSPACE/IDENTITY.md" >/dev/null
# IDENTITY.md - Who Am I?

- **Name:** Claw Demo
- **Creature:** Sandboxed OpenClaw assistant
- **Vibe:** Concise, practical, and demo-focused
- **Emoji:** 🦞

This identity was pre-seeded for the NemoClaw Omni vision sub-agent demo.
IDENTITY
    cat <<'USER' | docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee "$DATA_WORKSPACE/USER.md" >/dev/null
# USER.md - Human Context

- **Name:** Demo operator
- **Preference:** Keep answers concise and focus on verifying the OpenClaw Omni sub-agent recipe.
USER
fi

# 7. Make the task registry path writable when the current OpenClaw build expects it.
log "ensuring writable task registry path"
kexec bash -c 'mkdir -p /sandbox/.openclaw-data/tasks && chown -R sandbox:sandbox /sandbox/.openclaw-data/tasks && rm -rf /sandbox/.openclaw/tasks && ln -s /sandbox/.openclaw-data/tasks /sandbox/.openclaw/tasks'

log "verifying patched config"
kexec /bin/bash -lc 'python3 - <<"PY"
import json
import os
cfg = json.load(open("/sandbox/.openclaw/openclaw.json"))
providers = cfg["models"]["providers"]
agents = {agent["id"]: agent for agent in cfg["agents"]["list"]}
unused_plugins = [
    "acpx", "alibaba", "amazon-bedrock", "amazon-bedrock-mantle",
    "anthropic", "anthropic-vertex", "arcee", "bonjour", "browser",
    "byteplus", "chutes", "cloudflare-ai-gateway", "codex", "comfy",
    "copilot-proxy", "deepgram", "deepseek", "device-pair", "document-extract",
    "elevenlabs", "fal", "fireworks", "github-copilot", "google",
    "groq", "huggingface", "kilocode", "kimi", "litellm", "lmstudio",
    "memory-core", "microsoft", "microsoft-foundry", "minimax", "mistral", "moonshot",
    "ollama", "openai", "opencode", "opencode-go", "openrouter", "nvidia",
    "phone-control",
    "qianfan", "qqbot", "qwen", "runway", "sglang", "stepfun",
    "synthetic", "talk-voice", "tencent", "together", "venice", "vercel-ai-gateway",
    "vllm", "volcengine", "voyage", "vydra", "web-readability", "xai",
    "xiaomi", "zai",
]
plugin_entries = cfg.get("plugins", {}).get("entries", {})
checks = {
    "provider nvidia-omni": "nvidia-omni" in providers,
    "provider apiKey": providers.get("nvidia-omni", {}).get("apiKey", "").startswith("nvapi-"),
    "agent main": "main" in agents,
    "agent vision-operator": "vision-operator" in agents,
    "vision model": agents.get("vision-operator", {}).get("model", {}).get("primary", "").startswith("nvidia-omni/"),
    "vision workspace": agents.get("vision-operator", {}).get("workspace") == "/sandbox/.openclaw-data/workspace",
    "timeout": cfg["agents"]["defaults"].get("timeoutSeconds", 0) >= 300,
    "subagent concurrency": cfg["agents"]["defaults"].get("subagents", {}).get("maxConcurrent") == 4,
    "agents md": os.path.exists("/sandbox/.openclaw-data/workspace/AGENTS.md"),
    "tools": os.path.exists("/sandbox/.openclaw-data/workspace/TOOLS.md"),
    "auth data": os.path.exists("/sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json"),
    "auth active": os.path.exists("/sandbox/.openclaw/agents/vision-operator/agent/auth-profiles.json"),
    "plugin deps": os.path.islink("/sandbox/.openclaw/plugin-runtime-deps") or os.path.isdir("/sandbox/.openclaw/plugin-runtime-deps"),
    "plugins globally disabled": cfg.get("plugins", {}).get("enabled") is False,
    "memory plugin slot disabled": cfg.get("plugins", {}).get("slots", {}).get("memory") == "none",
    "unused plugins disabled": all(plugin_entries.get(plugin_id, {}).get("enabled") is False for plugin_id in unused_plugins),
}
for name, ok in checks.items():
    print(f"{name}: {ok}")
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("failed verification checks: " + ", ".join(failed))
PY'

cat > "$BACKUP_DIR/UNDO.txt" <<UNDO
To undo this demo patch for sandbox $SANDBOX:

  openshell policy set --policy "$BACKUP_DIR/policy-before.yaml" "$SANDBOX"
  docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- chmod 644 /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash
  docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- tee /sandbox/.openclaw/openclaw.json < "$BACKUP_DIR/openclaw-before.json" > /dev/null
  docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- /bin/bash -c 'cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash && chmod 444 openclaw.json .config-hash'
  docker exec "$DOCKER_CTR" kubectl exec -n openshell "$SANDBOX" -- rm -f /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json /sandbox/.openclaw/agents/vision-operator/agent/auth-profiles.json /sandbox/.openclaw-data/workspace/AGENTS.md /sandbox/.openclaw-data/workspace/TOOLS.md

If you used SEED_DEMO_IDENTITY=1, restore identity files from:
  "$BACKUP_DIR/openclaw-demo-identity-before.tar"
UNDO

log "done"
echo "Backup and undo instructions: $BACKUP_DIR"
