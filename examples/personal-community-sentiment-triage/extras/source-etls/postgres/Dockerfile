# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

FROM postgres:16

COPY init/01-init.sh /docker-entrypoint-initdb.d/01-init.sh
RUN chmod 644 /docker-entrypoint-initdb.d/01-init.sh
