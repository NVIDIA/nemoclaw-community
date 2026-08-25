# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The answer-shape instruction every submission is entitled to use.

Grading is deterministic, so it can only be fair if every system knows what a
gradeable answer looks like: short, current, and honest about gaps. Publishing
that instruction here — instead of letting each adapter invent its own — keeps
the comparison about memory quality rather than prompt luck. Adapters are free
to prepend their own scaffolding; they must not weaken these rules.
"""

ANSWER_CONTRACT = """Answer the question from the memory you built out of the corpus.

Rules:
1. Be short. Answer with the specific value asked for (a name, date, number,
   version, status), not a paragraph. One sentence is usually enough.
2. Give the CURRENT state. If a later document supersedes an earlier one, the
   later one is the answer; do not present the superseded value as still true.
3. If the corpus does not support an answer, say plainly that it is not in the
   corpus. Never guess. Something that was only scheduled has not happened.
4. Cite the document ids you relied on, exactly as they appear in the corpus
   (for example "E:2026-05-14T09-29-00__eba84193" or "S:D200JOR001_dm@2026-05-21").

Reply with a single JSON object and nothing else:
{"answer": "<your short answer>", "source_ids": ["<doc id>", ...]}
"""
