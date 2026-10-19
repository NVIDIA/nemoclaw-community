# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Negative-control agent: hands over a saved model instead of building one.

    PYTHONPATH=controls harbor run -p evals/<task> -a replay_agent:ReplayModel \\
      --ak model=controls/<task>/<negative>.FCStd -y
"""
from pathlib import Path

from harbor.agents.base import BaseAgent


class ReplayModel(BaseAgent):
    def __init__(self, *args, model: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = Path(model)

    @staticmethod
    def name() -> str:
        return 'replay-model'

    def version(self) -> str | None:
        return '1'

    async def setup(self, environment) -> None:
        pass

    async def run(self, instruction, environment, context) -> None:
        await environment.upload_file(self.model, '/app/model.FCStd')
