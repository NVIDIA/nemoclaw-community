# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate and journal one version-1 memory proposal read from standard input."""

import json
import sys

from memory_io import MemoryBlocked, MemoryConflict
from memory_pages import apply


def main():
    try:
        # Bound input before JSON parsing as well as rendered journal payloads.
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise MemoryConflict("proposal exceeds 8 MiB")
        result = apply(json.loads(raw))
    except (MemoryBlocked, MemoryConflict, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "blocked", "detail": str(exc)}))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
