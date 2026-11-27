# SPDX-License-Identifier: Apache-2.0

"""Validate and preserve the Captain's contextual independent-review decision."""


def include_required_review(plan):
    """Require a selected reviewer; never invent an assignment or its identity."""
    if not plan.get('reviewRequired'):
        return
    tasks = plan['tasks']
    if not tasks and plan.get('outcome') in ('partial', 'unavailable'):
        return
    reviewers = [task for task in tasks if task['role'] == 4]
    if not reviewers:
        raise ValueError('Independent review is required by the plan, but no reviewer is assigned. '
                         'Select a different available, suitably skilled agent in slot 4 within the three-specialist limit, '
                         'or explain why the required review cannot be provided before starting work.')
    originals = list(dict.fromkeys(key for task in tasks for key in task.get('inputs', [])))
    review = reviewers[0]
    review['inputs'] = list(dict.fromkeys(review.get('inputs', []) + originals))
    if any(task.get('useImages') for task in tasks):
        review['useImages'] = True
    # Casey chooses what is reviewed and its dependency order. A review of
    # intermediate evidence may itself be an input for a later implementer.
    if plan.get('answer'):
        plan['captainDraft'] = plan.pop('answer')


def review_finished(plan):
    output = plan.get('outputs', {}).get('4', {})
    return bool(4 in plan.get('calledRoles', []) and output.get('answer')
                and not output.get('incomplete') and output.get('handoffStatus') != 'missing')
