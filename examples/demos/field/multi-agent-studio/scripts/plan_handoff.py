# SPDX-License-Identifier: Apache-2.0

"""Required saved handoffs, checked independently of model completion claims."""
import re
from pathlib import PurePosixPath
from plan_artifacts import TEXT_TYPES


class PlanHandoffError(RuntimeError):
    """An invalid output declaration that the planner can correct before dispatch."""


def required_files(task):
    explicit = task.get('requiredFiles', [])
    if not isinstance(explicit, list) or len(explicit) > 12:
        raise PlanHandoffError('Invalid required handoff files in the plan.')
    paths = []
    for entry in explicit:
        # Accept a labelled path only when the other fields are explanatory text.
        # It still passes the same artifact boundary and type checks as a bare path.
        path = entry
        if isinstance(entry, dict) and set(entry) <= {'path', 'description', 'needs'}:
            if all(isinstance(value, str) for value in entry.values()):
                path = entry.get('path')
        if (not isinstance(path, str) or len(path) > 300 or not path.startswith('artifacts/')
                or any(part in ('', '.', '..') for part in path.split('/')) or '\\' in path
                or PurePosixPath(path).suffix.lower() not in TEXT_TYPES | {'.html'}):
            raise PlanHandoffError('Required handoff files must be supported files inside artifacts/.')
        paths.append(path)
    # The structured contract is authoritative, including an intentional empty
    # list for read-only work. References to upstream files are not new outputs.
    if 'requiredFiles' in task:
        return list(dict.fromkeys(paths))
    # Legacy plans: infer only an output-directed instruction, never a past
    # participle ("read the saved ...") or an input used to create something else.
    prose = task.get('task', '') + '\n' + task.get('expected', '')
    inferred = re.findall(
        r'(?:^|[.!?;\n])\s*(?:please\s+)?(?:save|write|create|produce|output|update|저장)\s+'
        r'(?:(?:[^\n.!?;]{0,80}\s+)?(?:to|as|into)\s+)?[`"\x27]?'
        r'(artifacts/[\w./-]+\.(?:md|txt|csv|json|py|js|css|html))\b', prose, re.I)
    return list(dict.fromkeys(p for p in inferred if not any(part in ('', '.', '..') for part in p.split('/'))))


def missing_files(task, sources, files):
    required = required_files(task)
    # The existing webpage collector can save a complete returned HTML document
    # under its own verified preview filename when native writing is unavailable.
    html_fallback = (sum(path.lower().endswith('.html') for path in required) == 1
                     and any(path.lower().endswith('.html') for path in files))
    return [path for path in required if not files or (path not in sources
            and not (path.lower().endswith('.html') and html_fallback))]
