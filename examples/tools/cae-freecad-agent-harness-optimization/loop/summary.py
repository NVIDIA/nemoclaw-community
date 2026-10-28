# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""loop/summary.py JOB [BASE_JOB]: one agent's runs on one split, and, with BASE_JOB, the keep rule
of the cad-experimenter skill (generated tasks): more runs passed, or as many runs and more
checks, with no check passing fewer times. VOID runs (publish.void_reason) are left out, and a
job (or BASE_JOB) with VOID or missing runs is INCOMPLETE (exit 1); with BASE_JOB, both jobs
must hold the same runs of the same tasks, or there is no decision."""
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from publish import grade, void_reason  # noqa: E402

FAMILIES = {t: v['family'] for t, v in json.loads((ROOT / 'evals' / 'splits.json').read_text())['tasks'].items()}


def load(job):
    trials = sorted(p for p in Path(job).glob('*__*') if p.is_dir())
    missing = json.loads((Path(job) / 'result.json').read_text())['n_total_trials'] - len(trials)
    runs, void = [], 0
    for trial in trials:
        if void_reason(trial):
            void += 1
            continue
        g = grade(trial)
        g['task'] = trial.name.rsplit('__', 1)[0]
        runs.append(g)
    return runs, void, missing


def stats(runs):
    per_check = Counter(c for g in runs for c in g['passed'])
    total = Counter(FAMILIES.get(g['task'], '?') for g in runs)
    ok = Counter(FAMILIES.get(g['task'], '?') for g in runs if g['reward'] == 1)
    ious = [g['iou'] for g in runs if g['iou'] is not None]
    return {'runs': len(runs), 'passed': sum(g['reward'] == 1 for g in runs), 'checks': sum(g['checks'] for g in runs),
            'of': sum(g['of'] for g in runs), 'mean_iou': round(sum(ious) / len(ious), 3) if ious else None,
            'per_check': dict(sorted(per_check.items())),
            'per_family_passed': {f: f'{ok[f]}/{total[f]}' for f in sorted(total)}}


def main():
    jobs = [load(job) for job in sys.argv[1:]]
    runs, void, missing = jobs[0]
    s = stats(runs) | {'void': void, 'missing': missing}
    print(json.dumps(s, indent=1))
    for job, (_, void, missing) in zip(sys.argv[1:], jobs):  # trials Harbor never wrote are missing
        if void or missing:
            sys.exit(f'INCOMPLETE: re-run the {void} VOID and {missing} missing runs of {job} first')
    if len(jobs) > 1:
        base = jobs[1][0]
        ours, theirs = Counter(g['task'] for g in runs), Counter(g['task'] for g in base)
        if ours != theirs:  # counts are compared, so both sides need the same runs of the same tasks
            sys.exit(f'NO DECISION: re-run the VOID runs first; extra runs here {dict(ours - theirs)}, '
                     f'in the base {dict(theirs - ours)}')
        b = stats(base)
        worse = [c for c in b['per_check'] if s['per_check'].get(c, 0) < b['per_check'][c]]
        better = s['passed'] > b['passed'] or (s['passed'] == b['passed'] and s['checks'] > b['checks'])
        print('KEEP' if better and not worse else 'DROP', f"passed {s['passed']} vs {b['passed']}, checks {s['checks']} vs {b['checks']}",
              f'worse checks: {worse}' if worse else '')


if __name__ == '__main__':
    main()
