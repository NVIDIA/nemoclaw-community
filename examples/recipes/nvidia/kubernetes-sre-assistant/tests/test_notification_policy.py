# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Human escalation noise controls exercise the real notification router."""
import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, os.environ.get('SRE_AUTOHEAL_TEST_SOURCE', str(Path(__file__).resolve().parents[1] / 'charts/sre-autoheal-agent/files/agent')))
from sre_autoheal.models import Incident
from sre_autoheal.notify import Message, Notifier, Section, build_message


class RecordingSink:
    def __init__(self, name):
        self.name, self.messages = name, []

    def send(self, message):
        self.messages.append(message)
        return True


class NotificationPolicyTests(unittest.TestCase):
    def test_escalation_includes_redacted_last_50_lines_inline(self):
        logs = '\n'.join(f'line-{index:03d} <error>' for index in range(70))
        logs += '\npassword=do-not-email-this'
        incident = Incident('id', 'fingerprint', {
            'resource': {'kind': 'Pod', 'name': 'model', 'namespace': 'test'},
            'severity': 'high', 'evidence': {'logs_tail': logs},
        }, None, 'heal_failed', 'Three attempts exhausted')
        message = build_message(incident, 'heal_failed', {}, {})
        excerpts = [section for section in message.sections if section.kind == 'code']
        self.assertEqual(len(excerpts), 1)
        self.assertEqual(len(excerpts[0].body.splitlines()), 50)
        self.assertNotIn('line-020', message.text)
        self.assertIn('line-022', message.text)
        self.assertIn('line-069', message.text)
        for rendered in (message.text, message.html, message.markdown):
            self.assertNotIn('do-not-email-this', rendered)
            self.assertIn('REDACTED', rendered)
        self.assertNotIn('<error>', message.html)
        self.assertIn('&lt;error&gt;', message.html)

    def test_escalation_without_logs_explicitly_reports_unavailable_evidence(self):
        incident = Incident('id', 'fingerprint', {
            'resource': {'kind': 'Deployment', 'name': 'model', 'namespace': 'test'},
            'severity': 'high', 'evidence': {},
        }, None, 'escalated', 'Safety policy denied')
        self.assertIn('Application logs were not available', build_message(incident, 'escalated', {}, {}).text)

    def test_low_severity_escalation_stays_in_audit_not_human_channels(self):
        email, stdout = RecordingSink('email'), RecordingSink('stdout')
        notifier = Notifier.build({'stdout': {'enabled': False}}, lambda name: '')
        notifier.sinks = [email, stdout]
        message = Message('heal_failed', 'Recovery failed', [], 'medium', {})
        self.assertEqual(notifier.send(message), {'stdout': True})
        self.assertEqual(email.messages, [])
        self.assertEqual(stdout.messages, [message])

    def test_high_and_critical_escalations_reach_admin(self):
        email = RecordingSink('email')
        notifier = Notifier.build({'stdout': {'enabled': False}}, lambda name: '')
        notifier.sinks = [email]
        for severity in ('high', 'critical'):
            message = Message('escalated', 'Human review', [], severity, {})
            self.assertEqual(notifier.send(message), {'email': True})
        self.assertEqual(len(email.messages), 2)

    def test_digest_mode_keeps_heals_in_audit_without_immediate_email(self):
        email, stdout = RecordingSink('email'), RecordingSink('stdout')
        notifier = Notifier.build({'stdout': {'enabled': False}, 'healed_delivery': 'digest'}, lambda name: '')
        notifier.sinks = [email, stdout]
        message = Message('healed', 'Recovered', [], 'high', {})
        self.assertEqual(notifier.send(message), {'stdout': True})
        self.assertEqual(email.messages, [])

    def test_raw_incident_is_not_rendered_in_human_messages(self):
        message = Message('escalated', 'Human review', [Section('text', 'Evidence', 'Timeout')],
                          'high', {'private_marker': 'must-not-render'})
        for rendered in (message.html, message.text, message.markdown):
            self.assertNotIn('must-not-render', rendered)
            self.assertNotIn('Raw incident JSON', rendered)


if __name__ == '__main__':
    unittest.main()
