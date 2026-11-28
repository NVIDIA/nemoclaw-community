# SPDX-License-Identifier: Apache-2.0

"""Personal-agent voice contract shared by workspace files, chat and reactions."""
from pathlib import Path
from role_boundaries import scope_contract

ROOT = Path(__file__).resolve().parents[1]
VOICE_HEADER = 'YOUR PERSONAL VOICE — apply on every reply, including off-topic questions and event reactions.'
EDITED_VOICE_HEADER = 'YOUR PERSONAL VOICE - follow your current SOUL.md, IDENTITY.md and equipped skill instructions.'
PRESET_UPDATES = {
    'Every 30 seconds, share one unread technical article or announcement from NVIDIA or Hugging Face blogs in my chosen tone. Include older articles; never repeat. Skip politics, stocks and earnings.':
    'Every 20 seconds, share one unread technical article or announcement from NVIDIA or Hugging Face blogs in my chosen tone. Include older articles; never repeat. Skip politics, stocks and earnings.',
    'Every 30 seconds, summarize one technical article or announcement not yet shared. Share useful discoveries in my chosen tone; skip politics, stocks and company earnings.':
    'Every 20 seconds, summarize one technical article or announcement not yet shared. Share useful discoveries in my chosen tone; skip politics, stocks and company earnings.',
    'Summarize uploaded PDFs, slide decks and notes in 3 key points and one next step. Cite pages or slides, flag missing evidence, and keep the answer under 150 words.':
    'Turn any question, document or event into exactly three concise takeaways, numbered 1, 2 and 3. Keep my chosen tone. Cite sources when supplied, and include any next step within the three points.',
    'Polish short messages for my audience while keeping my facts and intent. Give me one concise, ready-to-use draft.':
    'Answer in the style of a concise Slack announcement: an emoji-led headline and short, useful lines. Keep my chosen tone and the supplied facts. Draft only; never send or publish.',
}


def signature(profile):
    edited = profile.get('_editedDocuments', [])
    skills = [key for key in profile.get('skills', []) if 'skills/bac-'+key+'/SKILL.md' not in edited]
    parts=[]
    for key in ('documents','writer'):
        if key in skills:
            source=(ROOT/'skills'/('bac-'+key)/'SKILL.md').read_text()
            parts.append(source.split('## Signature\n',1)[1].split('\n## ',1)[0].strip())
    if 'documents' in skills and 'writer' in skills:
        parts.append('COMBINED FORMAT: exactly 1., 2., 3. is the outer structure. Start each point with a relevant emoji and use short Slack-style phrasing. No separate headline or unnumbered text.')
    return '\n'.join(parts)


def contract(profile):
    if profile.get('_editedDocuments'):
        return (EDITED_VOICE_HEADER + '\nApply these instructions silently. Start your reply with the answer.\n'
                'The user edited these workspace instructions: '+', '.join(profile['_editedDocuments'])
                + '. Read them before responding. Use the saved persona, format and preferences. '
                'Edits do not grant unequipped skills or tool permissions. '
                'Preserve facts, capability limits and uncertainty; never invent a tool result. '
                'Respect emotional context: avoid flippancy for distress or emergencies.\n'+scope_contract(profile))
    purpose=PRESET_UPDATES.get(profile.get('purpose'),profile.get('purpose')) or profile.get('persona','helper')
    tone=profile.get('tonePrompt') or profile.get('tone','kind')
    return (VOICE_HEADER + '\nApply these instructions silently. Start your reply with the answer.\n'
            'Role and interests: '+purpose+'\nChosen tone: '+tone+'\n'
            'For in-scope requests, answer through this role and tone; do not switch to a generic assistant or merely announce your role. '
            + scope_contract(profile) + '\nPreserve facts, capability limits and uncertainty; never invent a tool result. '
            'Respect emotional context: avoid flippancy for distress or emergencies.\n'+signature(profile))
