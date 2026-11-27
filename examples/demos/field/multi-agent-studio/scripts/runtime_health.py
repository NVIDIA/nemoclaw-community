# SPDX-License-Identifier: Apache-2.0

"""Bounded grace for transient local gateway delays, never for refused connections."""


class RuntimeHealth:
    def __init__(self):
        self.last_success = None
        self.failures = 0
        self.failure_since = None

    def observe(self, value, now):
        value = dict(value)
        # Older/test adapters without probe details retain their existing contract.
        probe = value.get('gatewayProbe')
        if probe is None:
            return value
        if probe == 'ok':
            self.last_success = now
            self.failures = 0
            self.failure_since = None
            state, usable = 'ready', True
        elif probe == 'timeout':
            self.failures += 1
            if self.failure_since is None:
                self.failure_since = now
            recent = self.last_success is not None and now - self.last_success < 30
            if recent:
                state, usable = ('ready' if self.failures == 1 else 'slow'), True
            else:
                state = 'unavailable' if now - self.failure_since >= 30 else 'slow'
                usable = False
        else:
            # Authentication, refused connections and malformed responses cannot
            # borrow a prior success. A later timeout must not revive them either.
            self.last_success = None
            self.failures = 0
            self.failure_since = None
            state, usable = 'unavailable', False
        if 'teamModel' in value:value['teamReady']=usable and bool(value['teamModel'])
        value.update(gatewayState=state, gateway=usable,
                     ready=usable and bool(value.get('model')))
        return value
