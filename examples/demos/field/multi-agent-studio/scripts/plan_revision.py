# SPDX-License-Identifier: Apache-2.0

"""One evidence-backed repair, restricted to specialists already in this plan."""
# Shared by planning, specialist work and review.
PLAN_TIME_BUDGET_SECONDS = 7 * 60
PLAN_REVIEW_RESERVE_SECONDS = 15
PLAN_REVISION_MIN_SECONDS = 35


class PlanBudgetExceeded(RuntimeError):
    pass


def read_revision(value, plan):
    if not isinstance(value, dict) or plan.get('revision'):
        raise RuntimeError('Only one revision is allowed for this collaboration.')
    role, evidence_role = value.get('role'), value.get('evidenceRole')
    called = plan.get('calledRoles', [])
    if (type(role) is not int or role not in called or role == 0 or str(role) not in plan.get('outputs', {})
            or type(evidence_role) is not int or str(evidence_role) not in plan.get('outputs', {})):
        raise RuntimeError('A revision must use a participating specialist and a saved contribution as evidence.')
    if value.get('severity') != 'blocking':
        raise RuntimeError('A revision is reserved for a concrete unmet requirement, not optional polish.')
    result = {'role': role, 'evidenceRole': evidence_role, 'severity': 'blocking'}
    for key, limit in (('issue', 1500), ('task', 2000), ('expected', 1500)):
        text = value.get(key)
        if not isinstance(text, str) or not 0 < len(text.strip()) <= limit:
            raise RuntimeError('A revision needs a specific issue, scoped assignment and acceptance criteria.')
        result[key] = text.strip()
    return result


def merge_delivery_files(previous, updates, source_map):
    """Latest accepted export per source path; retain untouched companions.

    The caller scopes both lists to one specialist. Immutable historical
    exports remain on disk and in the original contribution.
    """
    replaced = {source_map[path] for path in updates if path in source_map}
    old_pages = [p for p in previous if p.lower().endswith('.html')]
    new_pages = [p for p in updates if p.lower().endswith('.html')]
    # A complete fenced HTML fallback has no native filename. Only the single
    # existing page is unambiguous; never drop unrelated companion pages.
    fallback_replaces = (len(old_pages) == len(new_pages) == 1 and new_pages[0] not in source_map)
    retained = [p for p in previous if source_map.get(p) not in replaced
                and not (fallback_replaces and p in old_pages)]
    return list(dict.fromkeys(retained + updates))


def effective_outputs(plan):
    outputs = dict(plan.get('outputs', {}))
    revision = plan.get('revision', {})
    if revision.get('status') == 'delivered' and revision.get('output'):
        outputs[str(revision['role'])] = revision['output']
    return outputs


def stale_revision_pages(plan):
    """A revised upstream handoff does not update pages already built from it."""
    revision = plan.get('revision', {})
    if revision.get('status') != 'delivered':
        return []
    roles = [task['role'] for task in plan.get('tasks', [])]
    if revision.get('role') not in roles:
        return []
    later = roles[roles.index(revision['role']) + 1:]
    return [path for role in later for path in plan.get('webpages', {}).get(str(role), [])]


REVISION_INSTRUCTIONS = (
    '\nYou may request ONE targeted revision from a specialist who already participated, '
    'only when a saved contribution or review identifies a concrete defect that prevents an original requirement '
    'from being met. Prioritize missing deliverables, failure to load, broken primary interactions and '
    'materially misleading results. Minor rounding, chart styling or wording issues can be disclosed '
    'without another generation pass; do not describe known inaccuracies as correct. Explicit user '
    'accuracy requirements still apply. Optional polish, personal taste and unavailable tools are not '
    'reasons to repeat work. '
    'A generic request to read the file again, confirm it was saved, or verify every requirement is NOT a blocking defect. '
    'Successful saved-file evidence already establishes delivery, not browser execution. If no concrete failure '
    'has been observed, finish with any unperformed execution checks stated as limitations. '
    'Perform a necessary narrow source check yourself using the supplied readPath; do not send the author back '
    'just to confirm its implementation. Preserve any independent review explicitly requested by the user. '
    'Choose the appropriate participating expert for this problem, not a fixed researcher/programmer pair. '
    'Preserve their role scope. Do not add an agent, broaden the user request or repeat the whole workflow. '
    'If evidence already establishes the correction, revise the final deliverable instead of researching it again. '
    'For example, excluding an out-of-window paper from a webpage can use the supplied publication date. '
    'Revising an upstream brief alone will not update a webpage already built from it. '
    'No automatic second review or second revision will follow. If one scoped repair cannot produce a useful '
    'improvement, return the current result as partial with its limitations. '
    'For a justified revision return ONLY JSON {"done":false,"reason":"why this repair is essential",'
    '"revision":{"role":5,"evidenceRole":4,"severity":"blocking","issue":"specific observed unmet requirement",'
    '"task":"one bounded repair within this specialist expertise","expected":"how Casey can verify it"}}. '
    'The role numbers are schema examples only; choose from the actual participants. Otherwise finish normally. '
)


def revision_instructions(plan):
    """Do not suggest an absent reviewer/programmer in the control JSON example."""
    called = [role for role in plan.get('calledRoles', [])
              if str(role) in plan.get('outputs', {})]
    if not called:
        return ''
    return REVISION_INSTRUCTIONS.replace('"role":5,"evidenceRole":4',
        '"role":' + str(called[0]) + ',"evidenceRole":' + str(called[-1])) + (
        '\nAllowed revision roles and evidenceRole values for this request: ' + str(called) + '. '
        'Reading an existing brief to compose your final reply is your own work, not a specialist revision. '
        'Use the supplied readPath if a specific verification is needed; otherwise finish from the contribution.\n')
