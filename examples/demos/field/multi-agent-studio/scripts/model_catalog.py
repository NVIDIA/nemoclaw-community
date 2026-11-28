# SPDX-License-Identifier: Apache-2.0

"""Small NVIDIA catalog filter, not a tool-use or model-quality certification.

The inference catalog can label specialist and test deployments as chat models.
Use its advertised mode together with task/deployment names, without maintaining
a list of individual model IDs. Missing legacy metadata remains unknown; it does
not make a conversational model unsupported.
"""
from collections.abc import Mapping
import re


CONVERSATIONAL_MODES = frozenset(('chat', 'responses', 'completion'))
_TASK_TOKENS = frozenset((
    'embed', 'embedqa', 'embedding', 'embeddings', 'rerank', 'rerankqa',
    'reranker', 'ocr', 'paddleocr', 'parse', 'parser', 'parsing', 'translate',
    'translation', 'tts', 'speech', 'whisper', 'transcribe', 'transcription',
    'moderation', 'moderator', 'batch', 'realtime',
    'nvclip', 'pii', 'detector', 'detection',
))
_DEPLOYMENT_TOKENS = frozenset(('fake', 'eval', 'evals', 'evaluation'))
_TOKEN_SPLIT = re.compile(r'[/._:\-]+')


def _positive_integer(value):
    return type(value) is int and value > 0


def exclusion_reason(row, provider='nvidia', context_window=None):
    """Return an exclusion reason, or None for a selectable catalog candidate.

    Only NVIDIA receives mode/name/context filtering. Other providers retain
    their existing catalog behavior. Metadata-less saved catalogs are accepted
    unless their IDs identify a known specialist or test/evaluation task.
    """
    if not isinstance(row, Mapping):
        return 'Invalid model entry.'
    ident = row.get('id')
    if (not isinstance(ident, str) or not ident
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in ident)):
        return 'Model ID is missing or invalid.'
    if provider != 'nvidia':
        return None

    mode = row.get('mode')
    if mode is not None:
        if not isinstance(mode, str):
            return 'Invalid model mode.'
        mode = mode.strip().lower()
        if mode and mode not in CONVERSATIONAL_MODES:
            return 'Model mode is not conversational: ' + mode + '.'

    tokens = set(_TOKEN_SPLIT.split(ident.lower()))
    if ('safety' in tokens and tokens & {'content', 'guard'}) or 'nemoguard' in tokens:
        return 'Specialist model task: content safety.'
    specialist = tokens & _TASK_TOKENS
    if specialist:
        return 'Specialist model task token: ' + sorted(specialist)[0] + '.'
    if ({'page', 'elements'} <= tokens or {'table', 'structure'} <= tokens):
        return 'Specialist model task: document layout.'
    deployments = tokens & _DEPLOYMENT_TOKENS
    # "test" is a reserved deployment namespace, rather than every model name
    # containing that word (for example a local or fixture "test-model").
    if ident.lower().startswith('test/'):
        deployments.add('test')
    if deployments:
        return 'Test or evaluation deployment: ' + sorted(deployments)[0] + '.'
    # The serving catalog currently advertises Sora video models as chat.
    if 'sora' in tokens:
        return 'Video generation model family: sora.'

    input_limit = row.get('max_input_tokens')
    if (_positive_integer(context_window) and _positive_integer(input_limit)
            and input_limit < context_window):
        return ('Advertised input limit (%d) is below the required context (%d).'
                % (input_limit, context_window))
    return None


def filter_rows(rows, provider='nvidia', context_window=None):
    """Return eligible row copies in endpoint order, keeping exact model IDs."""
    try:
        iterator = iter(rows)
    except TypeError:
        return []
    return [dict(row) for row in iterator
            if exclusion_reason(row, provider, context_window) is None]


def public_metadata(row):
    """Project only bounded-type catalog metadata used by the model selectors."""
    if not isinstance(row, Mapping):
        return {}
    metadata = {}
    mode = row.get('mode')
    if isinstance(mode, str) and mode.strip():
        metadata['mode'] = mode.strip().lower()
    for field in ('max_input_tokens', 'max_output_tokens'):
        value = row.get(field)
        if _positive_integer(value):
            metadata[field] = value
    if type(row.get('supports_vision')) is bool:
        metadata['supports_vision'] = row['supports_vision']
    modalities = row.get('input_modalities')
    if isinstance(modalities, list) and 0 < len(modalities) <= 8 and all(isinstance(m, str) and len(m) <= 32 for m in modalities):
        metadata['input_modalities'] = [m.lower() for m in modalities]
    return metadata
