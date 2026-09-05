#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# The storage prerequisite, in one place for every connector.
#
# Decision 5 on #122 gates real message bodies on encryption at rest, and it is
# the same question whichever source is being connected. A second copy would be
# a second thing to keep in step, and the one nobody edited would go on
# approving what the other refused.
#
# Sourced by the setup scripts; runnable on its own to check a machine before
# connecting anything:
#
#     SANDBOX_STORAGE_PATH=/var/lib/docker \
#         bash scripts/require-encrypted-storage.sh

# The storage prerequisite, checked before anything is inspected or
# attached.
#
# It used to sit after the reuse early-exit, which meant a run that
# found a usable provider printed "Nothing to do" and exited 0 without
# ever checking it — reported as a successful setup on a machine whose
# store had never been looked at. The check belongs before the branch,
# because it is a property of the machine rather than of the run.
require_encrypted_storage() {
  # Attaching this provider is the moment real message bodies start landing in
  # the store, and the prerequisite is that they land on an encrypted volume.
  # Owner-only permissions are not that: they stop another account reading the
  # file on a running system and do nothing for a disk that is lost, imaged, or
  # backed up.
  #
  # Which volume is the whole question, and it is not one this script can guess.
  # `HERMES_HOME` inside a sandbox is an overlay with no block device behind it,
  # so encryption is unobservable from in there. On the host it depends on the
  # driver: Docker keeps sandbox storage under its data-root, a VM keeps it in a
  # disk image, Kubernetes in a volume — none of which is reliably `$HOME`. An
  # earlier version inspected `$HOME` and would have approved the wrong volume on
  # every one of those.
  #
  # So the path is asserted rather than inferred. `SANDBOX_STORAGE_PATH` names
  # where this sandbox's storage actually lives; the script then verifies *that*
  # path, which is a real check rather than a plausible one.
  storage_path="${SANDBOX_STORAGE_PATH:-}"
  if [[ -z "$storage_path" ]]; then
    echo "     where this sandbox's storage lives is not something this script"
    echo "     can determine — it differs by driver, and guessing would mean"
    echo "     checking the wrong volume."
    echo ""
    echo "Find it, then re-run with it named. For the Docker driver:"
    echo "  docker info --format '{{.DockerRootDir}}'"
    echo ""
    echo "  SANDBOX_STORAGE_PATH=<path> bash ${SETUP_SCRIPT:-scripts/setup-slack.sh}"
    echo ""
    echo "docs/encrypted-storage.md explains what to look for and why."
    exit 1
  fi
  if [[ ! -e "$storage_path" ]]; then
    echo "SANDBOX_STORAGE_PATH does not exist: $storage_path" >&2
    exit 1
  fi

  encrypted="unknown"
  if command -v findmnt >/dev/null 2>&1 && command -v lsblk >/dev/null 2>&1; then
    source_dev="$(findmnt -no SOURCE --target "$storage_path" 2>/dev/null || true)"
    if [[ -n "$source_dev" ]]; then
      if lsblk -no TYPE "$source_dev" 2>/dev/null | grep -q crypt; then
        encrypted="yes"
      else
        encrypted="no"
      fi
    fi
  fi

  case "$encrypted" in
    yes)
      echo "     $storage_path is on an encrypted volume" ;;
    no)
      echo "     $storage_path does NOT appear to be on an encrypted volume" ;;
    *)
      echo "     could not determine whether $storage_path is encrypted" ;;
  esac

  if [[ "$encrypted" != "yes" ]]; then
    echo ""
    echo "This recipe stores message subjects, senders and bodies once a"
    echo "connector is attached. See docs/encrypted-storage.md."
    echo ""
    if [[ "${STORE_ENCRYPTION_ACKNOWLEDGED:-0}" == "1" ]]; then
      echo "     STORE_ENCRYPTION_ACKNOWLEDGED=1 — continuing."
    else
      read -r -p "Type 'encrypted' to confirm the prerequisite is met: " ACK
      if [[ "$ACK" != "encrypted" ]]; then
        echo "Not confirmed. Nothing has been configured." >&2
        exit 1
      fi
    fi
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  require_encrypted_storage
fi
