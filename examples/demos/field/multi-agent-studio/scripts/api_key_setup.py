# SPDX-License-Identifier: Apache-2.0

"""Import the provider configuration supplied to Studio at startup."""
import json
from pathlib import Path
import sys

import provider_keys


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) not in (1, 2) or (len(arguments) == 2 and arguments[1] != '--optional'):
        print('Usage: api_key_setup.py api.json [--optional]', file=sys.stderr)
        return 2
    try:
        provider_keys.install(Path(arguments[0]))
    except provider_keys.InvalidProviderEntries as error:
        print(error, file=sys.stderr)
        return 0 if '--optional' in arguments[1:] else 1
    except json.JSONDecodeError as error:
        print(f'Invalid JSON in api.json at line {error.lineno}, column {error.colno}. '
              'Fix the file and start again. Saved provider settings were not changed.', file=sys.stderr)
    except ValueError:
        print('Invalid api.json file. Check its structure against api.json.example. '
              'Saved provider settings were not changed.', file=sys.stderr)
    except (OSError, RuntimeError):
        print('Could not read or save api.json. Check file permissions.', file=sys.stderr)
    else:
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
