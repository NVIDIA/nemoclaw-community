# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gate existing maintenance skills on a recovered, compatible memory store."""

from memory_operations import main


if __name__ == "__main__":
    raise SystemExit(main(["gate"]))
