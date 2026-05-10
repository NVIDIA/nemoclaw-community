#!/usr/bin/env bash
# Apply the Omni sub-agent configuration, then run the smoke test.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$DIR/../.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$DIR/../.env"
  set +a
fi

"$DIR/apply-omni-subagent.sh"
"$DIR/verify.sh"
