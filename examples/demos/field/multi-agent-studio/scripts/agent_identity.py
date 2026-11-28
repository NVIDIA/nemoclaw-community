# SPDX-License-Identifier: Apache-2.0

"""Stable persisted identities; cleanup must not depend on today's role catalog."""
import re


def valid_agent_id(value):
    return isinstance(value, str) and re.fullmatch(r'bac-[a-f0-9]{24}(?:-r(?:0|[1-9][0-9]*))?', value) is not None
