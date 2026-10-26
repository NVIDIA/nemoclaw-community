# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Harbor agent: runs the CAD agent in each task's container, next to headless FreeCAD.

    PYTHONPATH=harness harbor run -p evals -a cad_agent:CadAgent -m MODEL -n 4 [--ak agent_dir=DIR]
"""

import shlex
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent

HERE = Path(__file__).resolve().parent


class GatewayLost(RuntimeError):
    """The run was lost to the model gateway (run_agent.py): Harbor re-runs it when the job
    allows retries (--max-retries), and publish.py treats one still lost as VOID."""


class CadAgent(BaseInstalledAgent):
    """Uploads an agent folder (agent.yaml, skills/; default agent/) and runs it with
    harness/run_agent.py."""

    def __init__(self, *args, agent_dir: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_dir = Path(agent_dir) if agent_dir else HERE.parent / 'agent'

    @staticmethod
    def name() -> str:
        return 'cad-agent'

    async def install(self, environment) -> None:
        # The task image already holds FreeCAD and the agent runtime.
        await self.exec_as_agent(environment, 'command -v freecadcmd && python -c "import deepagents"')

    async def run(self, instruction: str, environment, context) -> None:
        await environment.upload_dir(self.agent_dir, '/agent')
        await environment.upload_file(HERE / 'run_agent.py', '/installed-agent/run_agent.py')
        # pipefail: the runner's exit code, not tee's, so a crash is not hidden.
        await self.exec_as_agent(
            environment, 'set -o pipefail; python /installed-agent/run_agent.py /agent '
            f'{shlex.quote(instruction)} 2>&1 | tee /logs/agent/run.log',
            env={'CAD_MODEL': self.model_name or ''})
        # The output may carry a docker warning too, so look for the field rather than parse.
        read = await self.exec_as_agent(environment, 'cat /logs/agent/outcome.json 2>/dev/null || true')
        if '"ended": "gateway"' in (read.stdout or ''):
            raise GatewayLost('lost to the model gateway (outcome.json)')
