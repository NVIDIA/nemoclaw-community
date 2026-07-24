#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Write a JSON manifest for a snapshot or trace tarball.

Sidecar to snapshot.sh and download-traces.sh. Same on-disk schema either way:
{version, captured_at, sandbox_name, source_path, tarball, tarball_bytes,
 file_count, excluded_files, note}. When file_count == 0 and --empty-note is
non-empty, that note is used instead of the default credential-filter note.
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tarball", required=True, help="Path to the .tar.gz")
    p.add_argument("--output", required=True, help="Manifest output path")
    p.add_argument("--ts", required=True, help="ISO timestamp")
    p.add_argument("--sandbox", required=True, help="Sandbox name")
    p.add_argument("--source-path", required=True, help="Original source dir inside sandbox")
    p.add_argument("--file-count", type=int, required=True)
    p.add_argument("--tarball-bytes", type=int, required=True)
    p.add_argument("--empty-note", default="",
                   help="Note to use when file_count == 0 (otherwise the default filter note applies).")
    p.add_argument("excluded", nargs="*", help="Files dropped by the credential filter (relative paths).")
    args = p.parse_args()

    excluded = [x for x in args.excluded if x]
    if args.file_count == 0 and args.empty_note:
        note = args.empty_note
    else:
        note = "File-level credential filter applied. Inspect with `tar tzf <path>`."

    manifest = {
        "version": 1,
        "captured_at": args.ts,
        "sandbox_name": args.sandbox,
        "source_path": args.source_path,
        "tarball": os.path.basename(args.tarball),
        "tarball_bytes": args.tarball_bytes,
        "file_count": args.file_count,
        "excluded_files": excluded,
        "note": note,
    }
    with open(args.output, "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
