# SPDX-License-Identifier: Apache-2.0

"""NVIDIA destinations selected by the host operator."""
import re
from urllib.parse import urlsplit

PUBLIC = 'https://integrate.api.nvidia.com/v1'


def valid_config_url(value):
    if not isinstance(value, str) or len(value) > 300:
        return False
    # A plain HTTPS origin and /v1. Reject userinfo, query strings and fragments.
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]+)?/v1/?', value):
        return False
    try:
        url = urlsplit(value)
        labels = url.hostname.split('.')
        return url.port != 0 and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)
    except ValueError:
        return False


def host_configured(value):
    if not valid_config_url(value):
        return False
    base = value.rstrip('/')
    if base == PUBLIC:
        return True
    import provider_keys
    return base == provider_keys.read().get('nvidia', {}).get('baseUrl')


def supported(value):
    """A host-configured endpoint or the one connected for this session."""
    if host_configured(value):
        return True
    if not valid_config_url(value):
        return False
    import runtime_settings
    import session_secrets
    session = session_secrets.get(runtime_settings.secret_key('nvidia'))
    return bool(session.get('apiKey')) and session.get('baseUrl') == value.rstrip('/')
