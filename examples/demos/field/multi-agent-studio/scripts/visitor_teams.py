# SPDX-License-Identifier: Apache-2.0

"""Bind Open Task assignments to real hired agents, with built-in specialists as backup.

Adapted from Paul Roeseler's personal_collaboration capture/validation approach.
Keep the current dispatcher so cancellation, verified handoffs and recovery are shared.
"""
import json
import re
from collections import Counter
from role_boundaries import TEAM_ROLE_BOUNDARY, skill_scope, implementation_scope

def standby_catalog():
    from studio import CREW_CATALOG
    return {i: member for i, member in enumerate(CREW_CATALOG)
            if i and member.get('planEligible', True) and not member.get('retired')}


ROLE_SKILLS = {i: tuple(member['skills']) for i, member in standby_catalog().items()}
BUILTIN_NAMES = {i: member['name'] for i, member in standby_catalog().items()}


def default_hired_slots(members):
    """Choose an omitted slot for a named single-skill hire; this never assigns an agent."""
    # Shell's opt-in slot belongs to the named standby. A hired researcher's
    # own protection setting still applies when using the ordinary research slot.
    catalog = standby_catalog()
    slots = {}
    for member in members:
        skills = tuple(member.get('skills', ()))
        matches = [role for role, equipped in ROLE_SKILLS.items()
                   if equipped == skills and not catalog[role].get('explicitRequestOnly')]
        if len(skills) != 1:
            continue
        if len(matches) == 1:
            slots[member['key']] = matches[0]
        elif not matches and skill_scope(member):
            # Hired-only support skills share the general support slot. The
            # hired profile supplies the tools and is still checked for scope.
            slots[member['key']] = 7
    return slots


def team_mode(data):
    """Old clients retain their boolean opt-in; new clients name the team explicitly."""
    from studio import Problem
    if 'teamMode' in data:
        mode = data['teamMode']
        if not isinstance(mode, str) or mode not in ('builtin', 'mixed', 'hired'):
            raise Problem('Choose Hired only or Hired + Standby.')
        return mode
    include = data.get('includeHiredAgents', bool(data.get('roster')))
    if type(include) is not bool:
        raise Problem('Include hired agents must be on or off.')
    return 'mixed' if include else 'builtin'


def hired_members(db, owner):
    rows = db.execute("SELECT id,profile FROM agents WHERE kind='personal' AND participant="
                      "(SELECT participant FROM agents WHERE id=?) AND profile IS NOT NULL AND deleting=0 "
                      "ORDER BY created,id", (owner,)).fetchall()
    return [{**json.loads(row['profile']), 'key': row['id'], 'role': 'Hired specialist'} for row in rows]


def capture(studio, db, owner, *, wait_for_setup=False):
    """Capture actual availability. Participation intent belongs to Casey's plan."""
    from studio import Problem
    all_members = hired_members(db, owner)
    import personal_models
    runtime = studio.runtime_status() if all_members else {}
    members, unavailable, preparing = [], [], []
    for member in all_members:
        identity = {'key': member['key'], 'name': member['name']}
        if not personal_models.ready(member, runtime, 'team'):
            unavailable.append({**identity, 'reason': personal_models.unavailable(member, 'team')})
            continue
        try:
            studio.require_available(db, member['key'])
            setup = db.execute("SELECT id, json_extract(payload,'$.registrationOnly') AS registrationOnly FROM jobs WHERE owner=? AND kind='prepare-agent' "
                               "AND status='running'", (member['key'],)).fetchone()
            if setup and setup['registrationOnly']:
                # The worker serializes this brief registration with the captured mission.
                studio.require_idle(db, member['key'], except_job=setup['id'])
                members.append(member)
            elif setup:
                if wait_for_setup:
                    # Exempt only setup. Personal work and other reservations still take priority.
                    studio.require_idle(db, member['key'], except_job=setup[0])
                    preparing.append(member)
                unavailable.append({**identity, 'reason': 'Preparing.'})
            else:
                studio.require_idle(db, member['key'])
                members.append(member)
        except Problem:
            unavailable.append({**identity, 'reason': 'Busy or unavailable.'})
    if not members and preparing:
        # next_job holds a queued goal until its roster's running setup has finished.
        waiting_keys = {member['key'] for member in preparing}
        return preparing, [row for row in unavailable if row['key'] not in waiting_keys]
    return members, unavailable


def unique_hired_names(members, unavailable):
    """Accept exact display names only when they identify one available hire."""
    counts = Counter(m['name'].casefold() for m in (*members, *unavailable) if m.get('name'))
    reserved = {name.casefold() for name in (*BUILTIN_NAMES.values(), 'Casey', 'builtin')}
    return {m['name']: m['key'] for m in members if m.get('name') and m.get('key')
            and counts[m['name'].casefold()] == 1 and m['name'].casefold() not in reserved
            and not re.fullmatch(r'[0-9a-f]{24}', m['name'], re.I)}


def available_standby_names(mode, members, unavailable):
    hire_names = {str(member.get('name', '')).casefold() for member in (*members, *unavailable)}
    return [name for name in BUILTIN_NAMES.values() if mode != 'hired' and name.casefold() not in hire_names]


def instructions(members, unavailable=(), mode='mixed'):
    from agent_runtime import collaboration_capabilities
    choices = [{**{key: m.get(key) for key in ('key', 'name', 'purpose', 'skills')},
                'skillScope': skill_scope(m), 'implementationScope': implementation_scope(m),
                **collaboration_capabilities(m)} for m in members]
    policy = ('HIRED AGENTS ONLY: Casey coordinates but cannot do specialist work. Assign every specialist task '
              'to an exact hired key below. Never assign a standby specialist. '
              'Their role numbers are assignment types only, not available people. If the core requested result '
              'is known to be impossible with this team, return tasks:[], outcome:"unavailable" and explain the missing capability, '
              'unless the user explicitly permits reduced scope. Do not silently '
              'switch teams. One hire may deliver a combined small implementation, but may not independently review itself. '
              if mode == 'hired' else
              'MIXED TEAM PRIORITY: assign a suitable hired agent below before any built-in specialist with the same needed skill. '
              'This is mandatory, not a suggestion. Select a standby specialist only when no unassigned suitable hire is available, '
              'or when the visitor explicitly names that built-in specialist. '
              'If a hire covers one requested part and standby covers another, split those tasks within the three-slot limit. '
              'Explicitly named built-in specialists must be kept when requested. ')
    return ('\nVISITOR TEAM SELECTION - overrides generic recommendations to pick Scout/Cody/Vera by name. ' + policy +
            'For hired agents the role number describes the assignment, '
            'and the agent field identifies the hire by exact key. For standby, put the exact standby name in agent and omit role. '
            'Each agent and role can appear only once. '
            + TEAM_ROLE_BOUNDARY + ' '
            'Every hired assignment must include roleFit, one short sentence naming the equipped skill that covers this actual work. '
            'Do not invent a skill or use purpose text to justify missing skills. '
            'implementationScope:"missing-coding" means Coding is not equipped. Do not assign coding or an HTML deliverable, '
            'even to a Programmer or custom developer, and even if write is available. '
            'Interpret participation from the whole current user request, including negation and corrections. '
            'Return requestedAgents and excludedAgents as arrays of identities: exact hired keys or the standby names '
            'Vera, Cody, Ada, Iris, Scout, Shell. requestedAgents contains only people the user asks to participate; '
            'excludedAgents contains only people the user asks to leave out. An incidental mention, filename, quoted '
            'example or optional suggestion does not make someone required. Use [] when there is no such instruction. '
            'Never assign an excluded or unavailable agent. A requested standby overrides hired priority only in mixed mode. '
            'For a requested agent you cannot assign because of skills, availability, team mode or the three-slot limit, '
            'include declinedAgents:[{"agent":"same identity","reason":"specific limitation and next step"}]. '
            'Do not list a declined agent in tasks. Do not silently replace a requested unavailable person. '
            'Explain each declined request in summary and the final answer, not only in JSON metadata. '
            'An independent reviewer must be a different agent. Keep assignments small and concrete: enough '
            'evidence for the requested result, a saved handoff, then stop. For research the shared ceiling is '
            'two searches or five direct fetches within the whole-task time budget; leave time for implementation. '
            'No optional polish or repeated verification.\nHired agents:\n' + json.dumps(choices, ensure_ascii=False) +
            '\nUnavailable hired agents (context only, cannot be assigned):\n' + json.dumps(unavailable, ensure_ascii=False) + '\n')


class TeamSelectionError(RuntimeError):
    """A planner response needs explicit identities before any work may start."""


class HiredPriorityError(TeamSelectionError):
    """Casey can choose a hire for this existing assignment without rewriting the plan."""

    def __init__(self, message, role, keys):
        super().__init__(message)
        self.role = role
        self.keys = keys

    def select_hire(self, reply, plan):
        from agent_reply import object_reply
        value = object_reply(str(reply))
        if 'selectedHire' not in value:
            return reply  # A full reconsideration follows the usual validation path.
        key, summary, fit = value['selectedHire'], value.get('summary'), value.get('roleFit')
        if (key not in self.keys or not isinstance(summary, str) or not summary.strip()
                or not isinstance(fit, str) or not fit.strip()):
            raise TeamSelectionError('Casey did not identify a suitable hire for the existing assignment.')
        updated = {field: plan[field] for field in ('outcome', 'answer', 'requestedFormats', 'unassignedRequirements',
                   'reviewRequired', 'requestedAgents', 'excludedAgents', 'declinedAgents') if field in plan}
        # validate_selection raises this correction only for a standby without
        # an explicit request. Its old selection is not a participation requirement.
        replaced = BUILTIN_NAMES[self.role]
        updated['requestedAgents'] = [agent for agent in plan.get('requestedAgents', []) if agent != replaced]
        tasks = [{**t, 'agent': key, 'roleFit': fit} if t['role'] == self.role else t for t in plan['tasks']]
        return json.dumps({**updated, 'summary': summary, 'tasks': planner_assignments(tasks)}, ensure_ascii=False)


def validate_planned_outputs(plan):
    formats = plan.get('requestedFormats', [])
    declared = [path for task in plan['tasks'] for path in task.get('requiredFiles', [])]
    # A coding assignment may use the existing verified HTML collector without
    # an exact planner-selected filename. Final completion still needs a saved page.
    implicit_html = any(task['role'] == 5 for task in plan['tasks'])
    missing = [kind for kind in formats if not (kind == 'html' and implicit_html)
               and not any(path.lower().endswith('.' + kind) for path in declared)]
    if plan['tasks'] and missing and not plan.get('unassignedRequirements'):
        raise TeamSelectionError('The original request requires saved ' + ', '.join(missing).upper() +
                                 ' output, but no assignment produces it. Include the appropriate available specialist '
                                 'and requiredFiles, or record why the team cannot produce it in unassignedRequirements. '
                                 'Do not omit the implementation after selecting an analyst or researcher; Casey cannot fill it in.')


def validate_selection(plan, members, unavailable=(), mode='mixed', *, request=''):
    try:
        validate_participants(plan, members, unavailable, mode, request=request)
    except TeamSelectionError as participant_error:
        # One repair turn must address both independent defects. A hire-only
        # correction preserves the files and cannot fix an omitted output.
        try:
            validate_planned_outputs(plan)
        except TeamSelectionError as output_error:
            raise TeamSelectionError(f'{output_error}\n{participant_error}') from participant_error
        raise
    validate_planned_outputs(plan)


def validate_participants(plan, members, unavailable, mode, *, request):
    available = {m['key']: m for m in members}
    known = {**{m['key']: m['name'] for m in unavailable if m.get('key')},
             **{m['key']: m.get('name', m['key']) for m in members},
             **{name: name for name in BUILTIN_NAMES.values()}}
    requested = set(plan.get('requestedAgents', []))
    excluded = set(plan.get('excludedAgents', []))
    if (requested | excluded) - known.keys() or requested & excluded:
        raise TeamSelectionError('Participation requests must identify known agents and cannot both request and exclude the same agent.')
    selected = {assignment_identity(t) for t in plan['tasks']}
    if selected & excluded:
        raise TeamSelectionError('The plan assigns an agent it also excludes. Re-read the request and correct the participation decision.')
    selected_hires = {assignment.get('agent') for assignment in plan['tasks']
                      if assignment.get('agent') not in (None, 'builtin')}
    if mode == 'mixed':
        for assignment in plan['tasks']:
            if assignment.get('agent') not in (None, 'builtin'):
                continue
            standby = assignment_identity(assignment)
            # Casey interprets intent. Its own roster choices cannot establish that
            # the visitor named a standby in preference to an available hire.
            if standby in requested and re.search(r'(?<![a-z0-9_])' + re.escape(standby) + r'(?![a-z0-9_])',
                                                  request, re.IGNORECASE | re.ASCII):
                continue
            skills = ROLE_SKILLS.get(assignment.get('role'), ())
            candidates = [member for member in members if member['key'] not in selected_hires | excluded
                          and any(skill in member.get('skills', []) for skill in skills)]
            if candidates:
                names = ', '.join(member.get('name', member['key']) for member in candidates)
                selectors = ', '.join(member['key'] for member in candidates)
                raise HiredPriorityError('Hired + Standby must use a suitable hired agent before the built-in '
                                         + BUILTIN_NAMES[assignment['role']] + '. Assign ' + names +
                                         ' to this ' + '/'.join(skills) + ' work (agent selector: ' + selectors +
                                         ', role: ' + str(assignment['role']) + '). Preserve the other valid assignments. Use the standby specialist only '
                                         'after every matching hire is already assigned or unavailable. '
                                         'Only a standby the user explicitly names in the original request overrides that priority.',
                                         assignment['role'], [m['key'] for m in candidates])
    seen = set()
    for assignment in plan['tasks']:
        key = assignment.get('agent')
        if mode == 'hired' and key in (None, 'builtin'):
            raise TeamSelectionError('Hired agents only is selected. Assign every specialist task to an available hired key; '
                                     'built-in specialists cannot participate. If the team cannot do the work, explain the missing capability.')
        if key is None:
            if members:
                raise TeamSelectionError('Identify who performs every task using agent: an exact hired key or "builtin". '
                                         'Role numbers identify the job, not the agent. Read the original request to assign each person.')
            continue
        if key == 'builtin':
            continue
        if key not in available:
            raise RuntimeError('Casey selected an agent outside the available hired team. No specialist was started.')
        if key in seen:
            raise TeamSelectionError('Each hired agent can perform only one specialist assignment. '
                                     'An independent reviewer must be a different agent.')
        if not skill_scope(available[key]):
            raise TeamSelectionError(available[key].get('name', 'This agent') + ' has no equipped specialist skill. '
                                     'Equip the skill required for this task or choose a suitably equipped agent.')
        if not isinstance(assignment.get('roleFit'), str) or not assignment['roleFit'].strip():
            raise TeamSelectionError('Explain how each hired assignment fits an equipped skill in roleFit. '
                                     'If it does not fit, decline it rather than reassigning its identity.')
        implements = assignment.get('role') == 5 or any(
            str(file).lower().endswith(('.html', '.htm')) for file in assignment.get('requiredFiles', []))
        if implements and implementation_scope(available[key]) != 'allowed':
            raise TeamSelectionError(available[key]['name'] + ' does not have Coding equipped. '
                                     'File tools do not grant Coding. Remove this coding/HTML assignment; '
                                     'use a suitable available agent or explain the missing expertise. '
                                     'Do not relabel implementation as research or analysis.')
        seen.add(key)
    declined = plan.get('declinedAgents', [])
    declined_keys = {m['agent'] for m in declined}
    if len(declined_keys) != len(declined) or declined_keys - known.keys() or declined_keys & selected:
        raise TeamSelectionError('Declined agents must be known agents, listed once and not assigned work.')
    missing = [known[key] for key in sorted(requested - selected - declined_keys)]
    if missing:
        raise TeamSelectionError('The draft lists a participation request without a matching assignment or decline for ' + ', '.join(missing) +
                                 '. Re-read the user request. Remove names you chose yourself from requestedAgents. For an actual request, assign that person the requested work or explain the limitation in declinedAgents.')


def assignment_identity(assignment):
    key = assignment.get('agent', 'builtin')
    return BUILTIN_NAMES.get(assignment['role']) if key == 'builtin' else key


def planner_assignments(assignments):
    """Show a prior selection using the same selectors Casey must return."""
    rows = []
    for assignment in assignments:
        row = dict(assignment)
        if row.get('agent', 'builtin') == 'builtin':
            row['agent'] = assignment_identity(assignment)
            del row['role']
        rows.append(row)
    return rows


def bind(plan, roster, members, unavailable=(), mode='mixed'):
    """Apply Casey's explicit choices. Never infer or rewrite roles from prose."""
    validate_selection(plan, members, unavailable, mode, request=plan.get('task', ''))
    available = {m['key']: m for m in members}
    bindings = {}
    for assignment in plan['tasks']:
        key = assignment.get('agent', 'builtin')
        if key != 'builtin':
            member = available[key]
            bindings[str(assignment['role'])] = member
            roster[assignment['role']] = member
        assignment['name'] = roster[assignment['role']]['name']
    plan['visitorBindings'] = bindings
    declined = {m['agent'] for m in plan.get('declinedAgents', [])}
    plan['requiredAgents'] = [m for m in members if m['key'] in plan.get('requestedAgents', []) and m['key'] not in declined]


def validate(studio, owner, member):
    from studio import Problem
    with studio.db() as db:
        row = db.execute("SELECT profile FROM agents WHERE id=? AND kind='personal' AND participant="
                         "(SELECT participant FROM agents WHERE id=?)", (member['key'], owner)).fetchone()
        if not row or not row['profile']:
            raise Problem('The selected agent is no longer in this studio.', 409)
        studio.require_available(db, member['key'])
    current = json.loads(row['profile'])
    if any(current.get(key) != member.get(key) for key in ('id', 'name', 'purpose', 'tonePrompt', 'skills', 'protection', 'model', 'taskModel', 'avatar')):
        raise Problem('The selected agent changed after the task was submitted. Start a new task.', 409)
    return current


def explicit_standby_instructions():
    return ('\nOPT-IN PROTECTED SPECIALIST: Shell (agent:"Shell") uses Web research inside OpenShell. '
            'Select Shell ONLY if the user explicitly asks that agent by name to participate in the current request. '
            'Talking about OpenShell, a shell command, a quoted example, a filename, an optional suggestion or excluding '
            'Shell is not a request for this agent. Infer intent from the whole request, including negation. '
            'Record an actual request as "Shell" in requestedAgents. Never choose Shell as a fallback or for ordinary '
            'research; use other available researchers. Hired-only mode still excludes every standby specialist. '
            'When assigning Shell a specific URL, ask for one direct read and an immediate handoff if it fails. Assess any confirmed OpenShell blocks against the handoff. '
            'Do not interrupt for an individual blocked URL when other permitted sources answered the assignment. '
            'If needed research remains blocked, the app pauses in Mission Control. The user reviews OpenShell Policy and chooses Continue. Only the user can approve '
            'website permissions. Continue resumes the SAME protected specialist. For a specific source, retry only that URL if its host is newly allowed. '
            'For open-ended research, try relevant newly allowed sites. Without access to a needed source, use existing evidence '
            'with explicit limitations; never assign another agent to retrieve the blocked source.\n')


def validate_explicit_standby(plan, *, previous_plan=None, eligible_names=()):
    from collaboration_plan import PlanSelectionError
    for task in plan.get('tasks', []):
        member = standby_catalog().get(task['role'], {})
        if (task.get('agent', 'builtin') == 'builtin' and member.get('explicitRequestOnly')
                and member['name'] not in plan.get('requestedAgents', [])):
            name = member['name']
            # A repair can omit the opt-in while retaining the very same assignment.
            # Only carry intent from the preceding parsed plan for this request.
            if (previous_plan and name in eligible_names
                    and name in previous_plan['requestedAgents']
                    and any(prior['role'] == task['role'] and prior.get('agent', 'builtin') == 'builtin'
                            for prior in previous_plan['tasks'])
                    and all(name not in candidate['excludedAgents']
                            and all(item['agent'] != name for item in candidate['declinedAgents'])
                            for candidate in (previous_plan, plan))):
                plan['requestedAgents'].append(name)
                continue
            raise PlanSelectionError(member['name'] + ' is opt-in only. Select this standby only when the user '
                'explicitly asks for that agent; record that intent in requestedAgents. Otherwise use another suitable agent.')
