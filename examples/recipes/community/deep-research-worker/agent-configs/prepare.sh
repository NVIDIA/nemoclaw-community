#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
workspace="${1:?Usage: bash prepare.sh <workspace reported by nemoclaw plan>}"
if [[ ! "$workspace" =~ ^nc-[a-f0-9]{16}$ ]]; then
  echo "Expected a NemoClaw workspace such as nc-0123456789abcdef" >&2
  exit 1
fi
image=ghcr.io/nvidia/nemoclaw/v1/openclaw@sha256:bd4d5483797673c83d1dc607893c6e61b84b92cc467a181c2c278614344c168d
# Refuse to alter a volume owned by a different deployment.
if docker volume inspect deep-research-assets >/dev/null 2>&1; then
  owner=$(docker volume inspect deep-research-assets --format '{{index .Labels "openshell.ai/sandbox-attachable-workspace"}}')
  [[ "$owner" == "$workspace" ]] || { echo "Asset volume belongs to another workspace" >&2; exit 1; }
fi
umask 077
mkdir -p .run/stage/skills/deep-research
python3 - <<'PYTHON'
from pathlib import Path
import secrets
run = Path('.run')
token = run / 'worker-token'
if not token.exists():
    token.write_text(secrets.token_urlsafe(48) + '\n')
token.chmod(0o600)
secret = token.read_text().strip()
if not secret or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in secret):
    raise SystemExit('Invalid worker token; restore the original token or remove it to rotate')
(run / 'worker.env').write_text('DEEPAGENTS_SERVICE_SECRET=' + secret + '\n')
(run / 'worker.env').chmod(0o600)
source = Path('../src/SKILL.md').read_text()
(run / 'stage/skills/deep-research/SKILL.md').write_text(
    source.replace('/sandbox/bin/deep-research', '/sandbox/research/deep-research'))
PYTHON
cp ../src/deep_research_client.py .run/stage/deep_research_client.py
cp .run/worker-token .run/stage/worker-token
cat > .run/stage/deep-research <<'WRAPPER'
#!/usr/bin/env bash
export DEEPAGENTS_ENDPOINT_URL=http://172.30.192.10:9050
export DEEPAGENTS_CREDENTIAL_FILE=/sandbox/research/worker-token
exec python3 /sandbox/research/deep_research_client.py "$@"
WRAPPER
chmod 755 .run/stage/deep-research
chmod 600 .run/stage/worker-token
docker volume create --label openshell.ai/sandbox-attachable=true \
  --label "openshell.ai/sandbox-attachable-workspace=$workspace" deep-research-assets >/dev/null
docker run --rm --user 0 --entrypoint /bin/sh \
  -v deep-research-assets:/assets -v "$PWD/.run/stage:/src:ro" "$image" \
  -c 'cp -R /src/. /assets/ && chown -R 10001:10001 /assets && chmod 755 /assets /assets/skills /assets/skills/deep-research && chmod 644 /assets/deep_research_client.py /assets/skills/deep-research/SKILL.md && chmod 600 /assets/worker-token && chmod 755 /assets/deep-research'
echo "Prepared assets for $workspace. Keep .run/worker-token to preserve worker access."
