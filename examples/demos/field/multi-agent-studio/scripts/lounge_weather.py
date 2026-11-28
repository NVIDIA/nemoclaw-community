# SPDX-License-Identifier: Apache-2.0
"""Provide a simple, explicitly located Lounge weather question with its native tool result."""
import json
import re

# Unmatched requests (including follow-ups, comparisons and date ranges) use normal agent tools.
CITY = r"(?P<city>[^\W\d_][\w .,'’\-]{0,79}?)"
EN_WEATHER = r"(?:(?:what(?:['’]s| is)|how(?:['’]s| is))\s+)?(?:the\s+)?(?:current\s+|today['’]s\s+)?weather"
QUESTIONS = (
    re.compile(EN_WEATHER + r"\s+(?:like\s+)?(?:in|for)\s+" + CITY + r"(?:\s+(?:right now|today))?", re.I),
    re.compile(CITY + r"\s+weather(?:\s+today)?", re.I),
    re.compile(r"(?:(?:현재|지금|오늘)\s*)?" + CITY + r"\s*(?:의\s*)?(?:오늘\s*)?날씨(?:는|가|를)?"
               r"\s*(?:어때요?|어떻게 돼요|알려\s*줘(?:요)?|어떤가요)?"),
)


def evidence(adapter, profile, kind, payload, session):
    if (kind != 'chat' or payload.get('modelStage', 'lounge') != 'lounge'
            or profile.get('protection') != 'standard' or 'weather' not in profile.get('skills', ())
            or profile.get('_editedDocuments') or payload.get('skill') not in (None, '', 'weather')
            or payload.get('images') or not callable(getattr(adapter, 'gateway', None))):
        return None
    request = payload['prompt'].strip().rstrip('?？!.').strip()
    for pattern in QUESTIONS:
        match = pattern.fullmatch(request)
        if match:
            break
    else:
        return None
    city = match['city'].strip(' ,')
    if not city or city.casefold() in {'here', 'there', 'my city', '여기', '거기', '그곳'}:
        return None
    try:
        result = adapter.gateway('/tools/invoke', {
            'sessionKey': 'agent:' + profile['id'] + ':openai-user:' + session,
            'tool': 'bac_weather', 'args': {'city': city, 'days': 1},
        }, timeout=25)
        if not result.get('ok') or result['result'].get('isError'):
            return None
        data = json.loads(result['result']['content'][0]['text'])
        if data.get('type') == 'forecast':
            # Today only. Retain the source, units and forecast timestamps for the answer.
            data['upcoming'] = data['upcoming'][:4]
        elif data.get('status') != 'ambiguous':
            return None
        return data
    except (RuntimeError, OSError, IndexError, KeyError, TypeError, ValueError):
        return None


def forecast_prompt(data, question):
    # The persistent OpenClaw session already carries this agent's role, voice and memory.
    if data.get('status') == 'ambiguous':
        facts = {'locations': data['locations']}
        instruction = 'Ask which of the matching places the user means.'
    else:
        place = data['location']
        facts = {'place': [part for part in (place['city'], place.get('regionName'), place.get('countryName') or place['country']) if part],
                 'updatedAt': data['updatedAt'], 'upcoming': data['upcoming'],
                 'dailyTemperatureSamples': data['dailyTemperatureSamples']}
        instruction = ('Describe the nearest forecast sample in plain language. Daily ranges cover available samples only. '
                       'Name the place and use only the supplied conditions and values. The studio adds the location and source links.')
    return ('Your bac_weather tool already ran. Reply briefly in the language of the question using your own voice. '
            + instruction + '\nWeather data: ' + json.dumps(facts, ensure_ascii=False, separators=(',', ':'))
            + '\nUser request: ' + question)


def source_line(data):
    if not data or data.get('type') != 'forecast':
        return ''
    place = data['location']
    names = (place['city'], place.get('regionName'), place.get('countryName') or place['country'])
    label = ', '.join(dict.fromkeys(name for name in names if name))
    return (f"{label} · [MET Norway]({data['source']}) · [GeoNames](https://www.geonames.org/)"
            " · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)")
