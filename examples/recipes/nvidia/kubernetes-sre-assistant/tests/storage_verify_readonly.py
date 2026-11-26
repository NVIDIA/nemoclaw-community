# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Replay recovery verification against the already-expanded disposable PVC.

Run via stdin inside the validation agent. Does not mutate Kubernetes or durable
incident memory. Uses current metrics and the actual PVC operation. Test success
email is optionally captured in the namespace-local SMTP catcher, never externally.
"""
import json
from sre_autoheal.config import load_config
from sre_autoheal.kube import KubeClient, ResourceRef
from sre_autoheal.memory import Memory, NullBackend
from sre_autoheal.notify import Notifier
from sre_autoheal.storage import OPERATION, StorageController

cfg = load_config()
client = KubeClient.build()
ns = 'sre-storage-validation-20261005'
pvc = client.get(ResourceRef('', 'v1', 'persistentvolumeclaims', ns, 'validation-data'))
actual = json.loads(pvc['metadata']['annotations'][OPERATION])
assert actual['outcome'] == 'healed', 'only replay an already completed validation operation'
assert cfg.get('notify.email.smtp_host') == 'storage-validation', 'only isolated test SMTP permitted'
memory = Memory(NullBackend(), {})
notifier = Notifier.build(cfg.section('notify'), lambda key: None)
controller = StorageController(cfg.section('storage'), client, memory, notifier, [ns])
record = controller._pending(pvc, {**actual, 'outcome': 'expansion_requested'},
                             controller.metrics(), [], writes_allowed=False)
controller._deliver()
print(json.dumps({'read_only_recovery_replay': record, 'kubernetes_mutations': False}))
assert record['outcome'] == 'healed', 'latest verification safeguards did not confirm recovery'
