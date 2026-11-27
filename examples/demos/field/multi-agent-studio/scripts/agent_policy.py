# SPDX-License-Identifier: Apache-2.0

"""Per-agent OpenShell policy operations. Attendees choose only curated public reads.

CLI contract: NVIDIA/OpenShell v0.1.4,
crates/openshell-cli/src/{main,run}.rs. Native runtime mapping comes from
OpenClaw 2026.11.3. Registry lookups and health probes are scoped to the target agent.
"""
import hashlib
from pathlib import Path
import json
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit

import agent_runtime as runtime
import ops_common as c

CATALOG = {
    'papers': {'title': 'arXiv papers', 'description': 'Find recent preprints and read their abstracts; no search API key.',
               'hosts': ['export.arxiv.org', 'arxiv.org']},
    'forecast': {'title': 'Weather forecast', 'description': 'Read MET Norway forecasts. City lookup works offline.',
                 'hosts': ['api.met.no']},
    'search': {'title': 'Wikipedia search', 'description': 'Search public Wikipedia articles without an API key.',
               'hosts': ['en.wikipedia.org']},
    'github': {'title': 'Public GitHub API', 'description': 'Read public project information; no account credentials.',
               'hosts': ['api.github.com']},
}

# Resolve older saved grants without suggesting event-specific destinations.
_LEGACY_CATALOG = {
    'weather': {'title': 'Weather & city lookup', 'description': 'Read live weather and look up a city.',
                'hosts': ['api.open-meteo.com', 'geocoding-api.open-meteo.com', 'wttr.in']},
    'zurich': {'title': 'Zurich visitor guide', 'description': 'Read public pages for event and travel ideas.',
               'hosts': ['www.zuerich.com']},
}


def destination_permission(host):
    """Exact public DNS names only; never wildcard, IP, URL or local-host grants."""
    if not isinstance(host, str):
        raise ValueError('Choose an exact public hostname.')
    host = host.lower().rstrip('.')
    if (len(host) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', host)
            or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid', '.example', '.home', '.lan'))):
        raise ValueError('Choose an exact public hostname.')
    return 'host:' + host


def permission_rule(key):
    if key in CATALOG:
        return CATALOG[key]
    if key in _LEGACY_CATALOG:
        return _LEGACY_CATALOG[key]
    if not isinstance(key, str) or not key.startswith('host:') or destination_permission(key[5:]) != key:
        raise ValueError('Choose an available public-read permission.')
    return {'title': key[5:], 'description': 'Requested destination. Approve this exact host only; redirects need their own approval.', 'hosts': [key[5:]]}


def individual_permissions(permissions):
    """Presets are approval shortcuts; saved network grants are exact hosts."""
    keys = set()
    for key in permissions:
        rule = permission_rule(key)
        keys.update(destination_permission(host) for host in rule['hosts'])
    return sorted(keys)


def policy_document(approved=()):
    if not isinstance(approved, (list, tuple)):
        raise ValueError('Choose an available public-read permission.')
    return {'version': 1, 'filesystem_policy': {'include_workdir': True,
            'read_only': ['/usr', '/lib', '/lib64', '/bin', '/sbin', '/proc', '/dev/urandom', '/etc', '/var/log'],
            'read_write': ['/sandbox', '/agent', '/tmp', '/dev/null']},
            'landlock': {'compatibility': 'best_effort'},
            'network_policies': {'bac_' + hashlib.sha256(key.encode()).hexdigest()[:20] if key.startswith('host:') else 'bac_' + key: {'name': 'bac-' + hashlib.sha256(key.encode()).hexdigest()[:20] if key.startswith('host:') else 'bac-' + key,
                'endpoints': [{'host': host, 'port': 443, 'protocol': 'rest', 'enforcement': 'enforce', 'access': 'read-only'} for host in permission_rule(key)['hosts']],
                'binaries': [{'path': '/usr/bin/curl'}]} for key in sorted(set(approved)) if permission_rule(key)['hosts']}}


def default_path():
    return runtime.root() / 'policies/default-deny.json'


def plugin_config():
    return c.read_json(runtime.config_path(), {}).get('plugins', {}).get('entries', {}).get('openshell', {})


def configured():
    try:
        entry = plugin_config()
        config = entry.get('config', {})
        command = config.get('command', 'openshell')
        return bool(entry.get('enabled') and shutil.which(command) and config.get('mode') == 'mirror'
                    and config.get('autoProviders') is False and not config.get('providers')
                    and config.get('policy') == str(default_path())
                    and c.read_json(default_path(), {}) == policy_document())
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def shell_command(*args):
    config = plugin_config().get('config', {})
    command = [config.get('command', 'openshell')]
    for field, flag in [('gateway', '--gateway'), ('gatewayEndpoint', '--gateway-endpoint'), ('workspace', '--workspace')]:
        if config.get(field):
            command += [flag, config[field]]
    return command + list(args)


def shell(*args, timeout=35):
    result = subprocess.run(shell_command(*args), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Fixed diagnoses only: stderr can contain credentials, policy bodies or
        # user command content. Never forward the raw subprocess output.
        detail = result.stderr.lower()
        if 'unexpected argument' in detail or 'unrecognized option' in detail:
            raise RuntimeError('The installed OpenShell CLI does not support a requested option. Check the app and OpenShell version compatibility; the protected request was not run.')
        if 'sandbox ownership check failed' in detail:
            raise RuntimeError('OpenShell sandbox ownership could not be verified. Creation was not sent; check the agent registration on the host.')
        raise RuntimeError('OpenShell could not complete this request. Check the gateway and policy on the host.')
    return result.stdout


def sandbox_registry(agent_id, retired=None):
    from agent_identity import valid_agent_id
    if not valid_agent_id(agent_id):
        raise RuntimeError('Choose a personal Multi-Agent Studio agent.')
    command = [str(runtime.root() / 'node/bin/node'), str(Path(__file__).with_name('sandbox_registry.mjs')),
               str(runtime.root()), agent_id]
    if retired is not None:
        command.append(json.dumps(retired))
    result = subprocess.run(command, env=runtime.environment(), capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('Could not read or update this agent’s native sandbox registry.')
    return json.loads(result.stdout) if retired is None else None


def runtimes(agent_id, *, probe=True):
    from agent_identity import valid_agent_id
    if not valid_agent_id(agent_id):
        raise RuntimeError('Choose a personal Multi-Agent Studio agent.')
    report = sandbox_registry(agent_id)
    if not isinstance(report, dict) or not isinstance(report.get('containers'), list) or any(not isinstance(row, dict) for row in report['containers']):
        raise RuntimeError('Invalid native sandbox registry response.')
    prefix = 'agent:' + agent_id
    matches = [row for row in report.get('containers', []) if row.get('backendId') == 'openshell'
               and isinstance(row.get('sessionKey'), str)
               and (row['sessionKey'] == prefix or row['sessionKey'].startswith(prefix + ':'))]
    for row in matches:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,62}', row.get('containerName', '')):
            raise RuntimeError('Invalid sandbox identity from the native runtime.')
    if probe:
        for row in matches:
            name = row['containerName']
            try:
                live = json.loads(shell('sandbox', 'get', name, '--output', 'json'))
            except RuntimeError:
                if name in sandbox_names():
                    raise
                row['running'] = False
                continue
            if not isinstance(live, dict) or not isinstance(live.get('phase'), str) or live.get('name', name) != name:
                raise RuntimeError('Unexpected sandbox status response.')
            row['phase'] = live['phase']
            row['running'] = live['phase'] == 'Ready'
    return matches


def sandbox_names(owner=None):
    """Read the complete selected gateway/workspace inventory; errors remain failures."""
    names, seen_tokens, token = set(), set(), ''
    for _ in range(100):
        selector = () if owner is None else ('--selector', 'bac-agent-id='+owner)
        try:
            page = json.loads(shell('sandbox', 'list', '--output', 'json', '--page-size', '100', '--page-token', token, *selector))
        except (ValueError, TypeError):
            raise RuntimeError('Unexpected sandbox inventory response.') from None
        if (not isinstance(page, dict) or not isinstance(page.get('sandboxes'), list)
                or not isinstance(page.get('next_page_token'), str)):
            raise RuntimeError('Unexpected sandbox inventory response.')
        for row in page['sandboxes']:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', row['name']):
                raise RuntimeError('Unexpected sandbox inventory response.')
            names.add(row['name'])
        token = page['next_page_token']
        if not token:
            return names
        if token in seen_tokens:
            raise RuntimeError('Sandbox inventory repeated a continuation token.')
        seen_tokens.add(token)
    raise RuntimeError('Sandbox inventory was not fully verified.')


def owned_sandbox_names(agent_id):
    """Find creation-labeled resources even after the native registry was lost."""
    from agent_identity import valid_agent_id
    if not valid_agent_id(agent_id):raise RuntimeError('Invalid cleanup identity.')
    if not plugin_config().get('config'):return set()
    return sandbox_names(agent_id)


def existing_runtimes(agent_id):
    """Ignore absent registry remnants only after a successful full inventory."""
    found = runtimes(agent_id)
    if any(not row.get('running') for row in found):
        existing = sandbox_names()
        # Stopped or unhealthy existing sandboxes still require verification.
        found = [row for row in found if row.get('running') or row['containerName'] in existing]
    return found


def network_rows(document):
    rows = []
    network = document.get('network_policies', {})
    if not isinstance(network, dict):
        raise ValueError('Invalid network policy response.')
    for key, rule in network.items():
        if (not isinstance(rule, dict) or not isinstance(rule.get('binaries', []), list)
                or not isinstance(rule.get('endpoints', []), list)
                or any(not isinstance(item, dict) for item in rule.get('binaries', []) + rule.get('endpoints', []))):
            raise ValueError('Invalid network rule response.')
        binaries = [b.get('path') for b in rule.get('binaries', [])]
        for ep in rule.get('endpoints', []):
            rows.append({'rule': key, 'host': ep.get('host'), 'port': ep.get('port'),
                         'access': ep.get('access'), 'protocol': ep.get('protocol'),
                         'enforcement': ep.get('enforcement'), 'binaries': binaries})
    return rows


def same_network(actual, expected):
    # Unknown provider/global entries must not silently count as our deny/allow policy.
    return actual.get('network_policies', {}) == expected.get('network_policies', {})


def same_policy(actual, expected):
    return (isinstance(actual, dict) and same_network(actual, expected)
            and actual.get('filesystem_policy') == expected['filesystem_policy']
            and actual.get('landlock') == expected['landlock'])


def read_policy(name):
    report = json.loads(shell('policy', 'get', name, '--full', '--output', 'json'))
    if not isinstance(report, dict) or report.get('sandbox') != name or not isinstance(report.get('policy'), dict):
        raise RuntimeError('OpenShell did not return this sandbox’s effective policy.')
    if report.get('policy_source') != 'sandbox':
        report['loaded'] = False
    else:
        if (type(report.get('version')) is not int or report['version'] < 1
                or type(report.get('active_version')) is not int):
            raise RuntimeError('Invalid effective policy revision.')
        # This response comes from OpenShell's effective sandbox configuration
        # and therefore reflects the policy actually active in the runtime.
        # Revision history can remain stale after activation in OpenShell 0.1.4.
        report['loaded'] = (report.get('status') == 'effective'
                            and report['active_version'] == report['version'])
    return report


def public_logs(name):
    logs = shell('logs', name, '--since', '2h', '-n', '500')
    events = []
    for line in re.sub(r'\x1b\[[0-9;]*m', '', logs).splitlines():
        action = re.search(r'(?:action[=:]\s*"?(allow|deny)\b|\b(ALLOWED|DENIED)\b)', line, re.I)
        host = re.search(r'(?:host|dst_host|destination)[=:]\s*"?([a-zA-Z0-9.-]+)', line) or re.search(r'->\s*([a-zA-Z0-9.-]+):[0-9]+', line)
        # L7 OCSF logs may omit the arrow: "HTTP:POST [MED] DENIED POST http://...".
        http_target = re.search(r'\b(?:GET|HEAD|OPTIONS|POST|PUT|PATCH|DELETE|CONNECT|TRACE)\s+(https?://[^\s]+)', line)
        hostname = host.group(1) if host else None
        if not hostname and http_target:
            try:
                hostname = urlsplit(http_target.group(1)).hostname
            except ValueError:
                pass
        if not action or not hostname:
            continue
        verdict = (action.group(1) or action.group(2)).lower()
        reason = ('dns-failed' if re.search(r'DNS resolution failed|failed to lookup address', line, re.I)
                  else 'destination-blocked' if 'engine:ssrf' in line.lower()
                  else 'policy-denied' if verdict in ('deny', 'denied') else None)
        method = re.search(r'\bHTTP:(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|CONNECT|TRACE)\b', line)
        events.append({'reason': reason, 'action': 'allow' if verdict in ('allow', 'allowed') else 'deny',
                       'method': method.group(1) if method else (http_target.group(0).split()[0] if http_target else None),
                       'host': hostname, 'binary': '/usr/bin/curl' if '/usr/bin/curl' in line else 'other process',
                       'source': 'OpenShell policy log', 'time': float(re.search(r'^\[([0-9]+(?:\.[0-9]+)?)\]', line).group(1)) if re.search(r'^\[([0-9]+(?:\.[0-9]+)?)\]', line) else None, 'fingerprint': hashlib.sha256(line.encode()).hexdigest()[:16]})
    return events[-30:][::-1]


def inspect(agent_id, protection, approved=()):
    result = {'mode': protection, 'checkedAt': time.time(), 'catalog': CATALOG,
              'requested': list(approved), 'rules': [], 'logs': [], 'sandboxes': [], 'policyDocuments': [],
              'filesystem': {'configured': policy_document()['filesystem_policy'], 'observed': [],
                             'status': 'not-verified', 'compatibility': 'best_effort'},
              'hostReady': configured(), 'status': 'standard' if protection == 'standard' else 'setup-required'}
    if protection == 'standard' or not result['hostReady']:
        return result
    entry = c.read_json(runtime.config_path(), {}).get('agents', {}).get('entries', {}).get(agent_id, {})
    if entry.get('sandbox', {}).get('mode') != 'all':
        result['status'] = 'awaiting-first-mission'
        return result
    try:
        found = existing_runtimes(agent_id)
        if not found:
            result['status'] = 'awaiting-first-mission'
            return result
        snapshots = []
        for row in found:
            name = row['containerName']
            policy = read_policy(name)
            snapshots.append(policy)
            result['policyDocuments'].append({'sandbox': name, 'revision': policy.get('version'),
                'source': policy.get('policy_source'), 'loaded': policy['loaded'],
                'running': bool(row.get('running')), 'document': policy['policy']})
            filesystem = policy['policy'].get('filesystem_policy', {})
            result['filesystem']['observed'].append({'sandbox': name, 'loaded': policy['loaded'],
                'running': bool(row.get('running')), 'policy': filesystem,
                'matchesConfigured': filesystem == policy_document()['filesystem_policy']})
            result['sandboxes'].append({'name': name, 'running': row.get('running'),
                                         'phase': row.get('phase'),
                                         'revision': policy.get('version'), 'loaded': policy['loaded'],
                                         'matchesRequest': same_policy(policy['policy'], policy_document(list(approved)))})
            result['rules'] += [{**r, 'sandbox': name} for r in network_rows(policy['policy'])]
            try:
                result['logs'] += public_logs(name)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                result['logsUnavailable'] = True
        result['filesystem']['status'] = 'policy-loaded' if all(
            x['loaded'] and x['running'] and x['matchesConfigured'] for x in result['filesystem']['observed']) else 'needs-review'
        result['status'] = 'applied' if all(x['loaded'] and x['matchesRequest'] and x['running'] for x in result['sandboxes']) else 'needs-review'
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        import logging
        failure = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else 'read-failed'
        logging.warning('OpenShell verification failed for %s: %s (%s)', agent_id, failure, type(error).__name__)
        result.update(status='unavailable', checkFailure=failure, error='Could not verify the agent’s live sandbox. Check OpenShell on the host, then refresh.')
    return result


def apply(agent_id, approved, *, allow_missing=False):
    if not configured():
        raise RuntimeError('Run ./bac dev openshell enable on the host first.')
    found = existing_runtimes(agent_id)
    if not found and not (allow_missing and not approved):
        raise RuntimeError('Run this protected agent once to create its sandbox, then approve access here.')
    directory = runtime.root() / 'policies'
    directory.mkdir(exist_ok=True, parents=True, mode=0o700)
    path = directory / (agent_id + '.json')
    c.write_json(path, policy_document(approved))  # JSON is also valid YAML; no extra parser dependency.
    if not found:
        return {'status': 'awaiting-first-mission'}
    for row in found:
        name = row['containerName']
        current = read_policy(name)
        if current.get('policy_source') != 'sandbox':
            raise RuntimeError('A host-wide policy controls this sandbox. Ask the host to review it.')
        # Skip only when the entire expected policy is loaded, including filesystem settings.
        if current.get('loaded') and same_policy(current['policy'], policy_document(approved)):
            continue
        try:
            shell('policy', 'set', name, '--policy', str(path), '--wait', timeout=75)
        except (RuntimeError, subprocess.TimeoutExpired):
            # A lost acknowledgement is not necessarily a failed activation.
            applied = read_policy(name)
            if not applied.get('loaded') or not same_policy(applied['policy'], policy_document(approved)):
                raise
        else:
            applied = read_policy(name)
        if not applied['loaded'] or not same_policy(applied['policy'], policy_document(approved)):
            raise RuntimeError('OpenShell has not confirmed the requested policy. Refresh to inspect what is applied.')
    return inspect(agent_id, 'openshell', approved)
