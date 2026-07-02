# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Direct test of the agentic proposer's write-restriction security property.

Exercises the real `create_deep_agent`/`FilesystemMiddleware`/`FilesystemPermission` pipeline
end-to-end (via a scripted fake chat model — no network call, no API key) to confirm a write
outside `/current/**` is actually denied and a write inside it actually succeeds. Requires the
`deepagents` extra; skipped entirely if it isn't installed, so the default (lightweight) test run
is unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("deepagents")

from hep.optimizers._agentic_proposer import build_backend_and_permissions  # noqa: E402


def test_write_permission_denies_outside_current(tmp_path: Path) -> None:
    from deepagents.graph import create_deep_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, HumanMessage

    class _FakeToolCallingChatModel(GenericFakeChatModel):
        """GenericFakeChatModel with a no-op bind_tools — create_deep_agent calls it."""

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001, ARG002
            return self

    workspace_root = tmp_path / "workspace"
    (workspace_root / "current").mkdir(parents=True)
    (workspace_root / "current" / "profile.py").write_text("# original\n", encoding="utf-8")

    sdk_dir = tmp_path / "sdk"
    sdk_dir.mkdir()
    (sdk_dir / "readme.txt").write_text("do not touch\n", encoding="utf-8")

    backend, permissions = build_backend_and_permissions(
        workspace_root=workspace_root, read_only_routes={"/sdk/": sdk_dir}
    )

    # edit_file, not write_file: write_file refuses to overwrite a file that
    # already exists (it's create-only) — /current/profile.py and
    # /sdk/readme.txt are both pre-seeded above, so exercising the
    # write-permission check on an existing file needs edit_file, which is
    # what a real agent would use to modify a file it just read.
    fake_model = _FakeToolCallingChatModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "edit_file",
                            "args": {
                                "file_path": "/sdk/readme.txt",
                                "old_string": "do not touch",
                                "new_string": "hacked",
                            },
                            "id": "call_1",
                            "type": "tool_call",
                        },
                        {
                            "name": "edit_file",
                            "args": {
                                "file_path": "/current/profile.py",
                                "old_string": "# original",
                                "new_string": "fixed",
                            },
                            "id": "call_2",
                            "type": "tool_call",
                        },
                    ],
                ),
                AIMessage(content="Done."),
            ]
        )
    )

    agent = create_deep_agent(model=fake_model, backend=backend, permissions=permissions)
    agent.invoke({"messages": [HumanMessage(content="edit files")]})

    # The write outside /current/** must have been denied; the file is untouched.
    assert sdk_dir.joinpath("readme.txt").read_text(encoding="utf-8") == "do not touch\n"
    # The write inside /current/** must have succeeded.
    assert workspace_root.joinpath("current", "profile.py").read_text(encoding="utf-8") == "fixed\n"
