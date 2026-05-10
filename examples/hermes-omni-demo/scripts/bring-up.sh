#!/usr/bin/env bash
# Configure the existing Hermes sandbox, then launch the host UI.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$DIR/../.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$DIR/../.env"
  set +a
fi

"$DIR/setup.sh"
"$DIR/start.sh"
