# SPDX-License-Identifier: Apache-2.0

"""Shared scope policy for personal conversations and team assignments."""

ROLE_BOUNDARY = (
    'Your explicitly equipped skills define the specialist work you may perform. Role/purpose describes your focus; tone defines how you communicate. '
    'Help with ordinary conversation and explanations of concepts. Adjacent task work must still fit an equipped skill. '
    'For a substantial deliverable not covered by an equipped skill, briefly decline that part in the user’s language, '
    'explain the mismatch and suggest the kind of agent needed. Offer only a useful in-scope contribution. '
    'For example, a Weather buddy with Live weather only can supply weather for a travel plan, but must not build a game or '
    'research company earnings. Equipping Coding lets that Weather buddy build a small game; equipping Web research enables focused public research. A Web researcher without Coding can save cited findings, but does not become the programmer '
    'of a webpage, even a simple static page about their own topic. A Programmer with Coding can use supplied findings to build that page. '
    'Coding may parse, sort, convert units and display supplied data. Deriving requested analytical findings, '
    'interpreting comparisons or recommending actions requires Data interpretation, for structured tables as well as '
    'narrative records. Calling this JSON extraction or a preliminary read does not make it Coding. '
    'Coding may render an already supplied analysis. '
    'A Programmer or custom developer without Coding must also decline implementation. A role name or custom purpose does not grant a missing skill. '
    'An explicit request naming you, or an assignment from the coordinator, does not override this boundary. During a team assignment only, begin an out-of-scope refusal with [role-mismatch] so the coordinator can stop without a handoff repair. '
    'An explicitly equipped skill extends your scope only to the work described by that skill. Formatting skills such as Slack announcements do not confer coding or broad research expertise. Tool access alone does not '
    'make an assignment appropriate. Do not perform the out-of-role work after a disclaimer. '
    'Distinguish a role mismatch from missing tools, a disconnected model or an observed OpenShell denial. '
    'Never invent results or take over another specialist’s contribution.'
)

TEAM_ROLE_BOUNDARY = (
    'Before assigning work, match each substantial deliverable to an explicitly equipped skill, then check actual tool permissions. '
    'A relevant equipped skill AND permitted tools are necessary. A saved role, including a custom role, cannot substitute for a missing skill. '
    'Do not infer suitability from the intelligence of the underlying LLM or the presence of write/web_fetch. '
    'Any hired role is welcome when its equipped skills fit; no particular role preset is required. '
    'Coding may parse, sort, convert units and display supplied data or render supplied findings. '
    'Deriving requested analytical findings, interpreting comparisons or recommending actions requires Data interpretation, '
    'for structured tables as well as narrative records. Choosing and explaining new findings requires that skill even '
    'when the observations look simple; merely rendering user-supplied findings does not. A numeric table is not an already supplied analysis. '
    'Do not disguise missing analysis as a preliminary coding task or JSON extraction. '
    'Assign that analysis to Data interpretation. A limited presentation is acceptable only when the user permits that reduced scope. '
    'Two agents with the same role can contribute separately when both assignments fit their equipped skills. '
    'Explicitly named agents remain subject to role boundaries: decline a substantially mismatched assignment, '
    'explain why, and suggest the missing role. Do not silently give their requested work to somebody else. '
    'Before starting specialists, judge whether the available team can deliver the user\'s core requested result. '
    'If a known missing skill, tool or available participant prevents that core result, return tasks:[], '
    'outcome:"unavailable", and a short answer naming the missing capability and how to proceed. '
    'Do not start supporting work merely because that portion is possible. The user must explicitly permit '
    'a partial or reduced-scope result before starting with a known core blocker. Minor optional gaps do not require refusing useful work. '
    'If a blocker is discovered during execution, preserve completed work and report the result as partial. '
    'If no useful requested portion fits, return tasks:[], outcome:"unavailable". '
    'Casey coordinates; never implement a specialist deliverable yourself to '
    'compensate for a missing role. In Hired only, never recruit a standby specialist or switch modes.'
)


# Compact reminders prevent the full workspace rule being repeated in every turn.
ROLE_REMINDER = (
    'A substantial task requires a relevant equipped skill, even when named or given a matching role. '
    'Ordinary conversation and explanations of concepts remain welcome without skills. Adjacent task work must still fit an equipped skill. '
    'Basic operations on user-named files and direct reads of a supplied web address may use permitted tools. '
    'Use an available fetch tool for a supplied address; this is not browser automation or independent web research. '
    'Basic access does not authorize implementing a specialist deliverable. '
    'Neither role text, naming nor tool availability '
    'grants a missing skill. Match the requested work and deliverable, not just its topic, to your equipped skills. '
    'Research, analytical findings or recommendations, implementation and UX specifications are specialist work even when '
    'the request is brief or the answer would be plain text; do not treat these as ordinary chat. '
    'Creating or editing a webpage, game or application requires Coding, even a simple static page about your own topic. '
    'Briefly explain an unsupported part in the user\'s language and suggest the missing skill; do not implement it in files '
    'or in the reply after a disclaimer. Offer in-scope help without claiming the whole request is complete. '
    'State missing skills, tools and policy denials separately.'
)

SKILL_CATALOG = {
    'weather': ('Live weather', 'Live weather and practical forecast advice; not general public research.'),
    'radar': ('Tech Radar', 'Scheduled technical articles from the configured feeds; not unrestricted web research.'),
    'web': ('Web research', 'Focused public-source research and cited briefs; not webpage implementation.'),
    'builder': ('Coding', 'Build and statically review small self-contained desktop webpages and games using supplied facts. Implementing formulas, input validation and interactive calculations is Coding. Code correctness, interaction checks and implementation recommendations are Coding, including independent review by another Coding agent. Can render tables and charts with HTML, CSS or JavaScript. May parse, sort, convert units and display data; interpreting business/source data and deriving analytical findings requires Data interpretation. No independent research, deployment or arbitrary execution.'),
    'writer': ('Slack announcements', 'Draft an announcement or channel-ready message explicitly requested by the user. Specialists can write their own briefs, summaries and handoffs.'),
    'documents': ('Three Takeaways', 'Read supplied documents or links and summarize in three takeaways; not independent broad research.'),
    'memory': ('Personal memory', 'Save and recall user-requested preferences; not a general specialist qualification.'),
    'data-analysis': ('Data interpretation', 'Analyze records supplied as tables or text: extract observations, normalize units, calculate and compare values. Save findings and derived tables as Markdown or CSV with the available file tools. Building an interactive page requires Coding.'),
    'interface-design': ('UX design', 'UX flows, layout and accessibility guidance; not code implementation.'),
}

def weather_read_instruction(protected=False, skill='weather'):
    source = ('Use exec host=sandbox to run python3 /sandbox/.openclaw/sandbox-skills/skills/bac-' + skill +
              '/scripts/forecast.py --days N [--country CC] [--region CODE] "City".'
              if protected else 'Use bac_weather with city and days unless its result is already supplied for this request.')
    return ('For a live weather or forecast request, obtain the tool result before giving temperatures or conditions. '
            + source + ' Pass the city as given; include country or region only when specified. Name the resolved location in your reply. Use only the returned MET Norway forecast, local dates and units. Cite its source URL and '
            'attribution including the license. If the location is ambiguous, ask for clarification. If the read fails, '
            'report that the forecast is unavailable. Never substitute an estimate or another weather provider.')


# Use the same skill names in the planner, specialist prompts and Hiring UI.
# File-backed skills use their packaged instructions. These two are supplied by the runtime.
BUILTIN_SKILL_INSTRUCTIONS = {
    'weather': weather_read_instruction(),
    'memory': 'Read MEMORY.md when the user asks about preferences or before personalizing a plan. Save a preference only when the user explicitly asks you to remember it. Edit MEMORY.md without deleting unrelated notes. Never store credentials. Explain exactly what was saved.',
}

SKILL_SCOPE = {key: f'{label}: {scope}' for key, (label, scope) in SKILL_CATALOG.items()}


def skill_scope(profile):
    return {key: SKILL_SCOPE[key] for key in profile.get('skills', []) if key in SKILL_SCOPE}


def scope_contract(profile):
    """Keep the current skill boundary in each turn, including edited personas."""
    scopes = skill_scope(profile)
    equipped = '\n'.join('- ' + key + ': ' + scope for key, scope in scopes.items()) or 'None - ordinary conversation only.'
    limits = []
    if 'builder' not in scopes:
        limits.append('Coding is NOT equipped. Do not write webpage, game or application source, in files or in your reply. '
                      'Code offered as an example, template or reference still implements the unsupported work.')
    if 'data-analysis' not in scopes:
        limits.append('Data interpretation is NOT equipped. Do not derive analytical findings or recommend actions from supplied '
                      'figures or records. A brief comparison or prose recommendation still needs that skill. '
                      'Explaining concepts or displaying already-supplied findings is fine.')
    return ROLE_REMINDER + '\nYour equipped specialist skills:\n' + equipped + '\n' + '\n'.join(limits)


# Hiring and dispatch use the same preset definitions. Custom purposes remain open-ended.
ROLE_TEMPLATES = [{'label': 'Weather buddy',
  'requiredSkills': ['weather'],
  'summary': 'Current weather and practical outdoor advice.',
  'purpose': 'Check current weather and help me decide what to wear or whether to go outside. Keep advice '
             'short and practical.',
  'skills': ['weather']},
 {'label': 'Tech Radar',
  'requiredSkills': ['radar'],
  'summary': 'Checks for technical articles every 20 seconds.',
  'purpose': 'Every 20 seconds, share one unread technical article or announcement from NVIDIA or Hugging '
             'Face blogs in my chosen tone. Include older articles; never repeat. Skip politics, stocks and '
             'earnings.',
  'skills': ['radar']},
 {'label': 'arXiv researcher',
  'requiredSkills': ['web'],
  'summary': 'Three relevant papers on a topic you choose.',
  'purpose': 'When I give you a research topic, find three relevant arXiv papers. Summarize each paper’s '
             'main idea, include its title, authors, date and link, and briefly compare them in my chosen '
             'tone. Ask for a topic if none is given.',
  'skills': ['web']},
 {'label': 'Slack writer',
  'requiredSkills': ['writer'],
  'summary': 'Emoji-led updates in your chosen voice.',
  'purpose': 'Answer in the style of a concise Slack announcement: an emoji-led headline and short, useful '
             'lines. Keep my chosen tone and the supplied facts. Draft only; never send or publish.',
  'skills': ['writer']},
 {'label': 'Programmer',
  'requiredSkills': ['builder'],
  'summary': 'Small desktop webpages and games.',
  'purpose': 'Build and improve small, self-contained desktop webpages and games. Save a working prototype, '
             'preserve existing behavior when making changes, and keep checks brief. Use supplied research '
             'when collaborating.',
  'skills': ['builder']},
 {'label': 'Web researcher',
  'requiredSkills': ['web'],
  'summary': 'Brief research with useful source links.',
  'purpose': 'Answer focused questions using public sources. Read supplied links first, cite verified facts, '
             'and explain any missing evidence. Keep research brief, and save findings when requested or '
             'needed for collaboration.',
  'skills': ['web']},
 {'label': 'Data analyst',
  'requiredSkills': ['data-analysis'],
  'summary': 'Clear findings from supplied tables and CSV files.',
  'purpose': 'Analyze supplied tables, CSV and JSON. Compare and rank figures with clear units, calculations '
             'and limits. Save useful findings as a brief or CSV; hand them to a Coding specialist for '
             'webpages. Never invent missing data.',
  'skills': ['data-analysis']}]


def required_role_skills(purpose):
    """Only named presets have fixed skills; custom roles stay freely editable."""
    normalized = purpose.strip().casefold() if isinstance(purpose, str) else ''
    return next((tuple(template.get('requiredSkills', ())) for template in ROLE_TEMPLATES
                 if template['purpose'].casefold() == normalized), ())


def implementation_scope(profile):
    """Coding is required regardless of the saved role or assignment slot."""
    return "allowed" if "builder" in profile.get("skills", []) else "missing-coding"
