# Storage auto-heal implementation ledger

Approved: 85% sustained utilization, 15% growth, recommendation by default,
opt-in automatic PVC expansion. PVC only; guest growth is manual admin/owner work.
Publication update (October 5, 2026): the operator explicitly authorized committing
and pushing this implementation to the fork branch and updating upstream PR #197.
This supersedes the earlier publication hold, not the remaining validation gaps:
successful native Kubernetes CSI expansion and live guest follow-up remain unverified.
The entries below retain the chronology of implementation and validation.

## Tasks

1. RED/GREEN: metrics validation, quantity arithmetic, policy and preflight.
2. RED/GREEN: concurrent-safe PVC expansion, durable state, verification,
   notification retry without repeating mutation, KubeVirt guest observation.
3. Integrate agent cycle, scoped Helm RBAC/configuration, docs and regressions.
4. Deploy new, isolated storage-controller releases on both selected clusters.
5. Review evidence; publish only after complete validation.

## Rulings

- Scope: deploy the auto-heal child chart under new release names, not another
  full Hermes/community backend. This validates the changed controller without
  duplicating existing interactive assistants.
- Existing state: preserve the unrelated ledger_rag/run.py mode change and the
  Hermes CoCo testing worktree. A fresh local backup was retained before edits.
- Guest access: use read-only KubeVirt filesystemlist with exact volume/device
  mapping. Do not run SSH commands, growpart, resize2fs, or reboot in this phase.
  Unverified guest growth is a partial outcome requiring human action.
- Kubernetes discovery: local-path has no volume-expansion capability. Test
  recommendation and rejected automation there; do not silently install a new
  privileged CSI driver or push while live-expansion validation is incomplete.
- State: PVC UID and resourceVersion guard an atomic size+operation-annotation
  patch. Pending/failed operations remain locked until human reconciliation;
  notification retries never repeat the resize.

## Evidence

Implementation is uncommitted. No publication authorized until validation.

- Regression tests reproduced and fixed: nonpersistent memory acceptance,
  metrics reporting filesystem capacity larger than PVC capacity, direct
  controller pause/observe bypass, original size missing in terminal email,
  watch-mode configured namespaces omitted, missing collector-error escalation,
  ephemeral Helm memory and custom metrics CA mounting.
- Recipe suite passed 100 tests in an isolated copy before the last collector/CA
  additions. Final suite and live evidence will be recorded below.
- OpenShift fixture uses real mounted-PVC statvfs. Native Kubernetes explicitly
  uses synthetic 88% utilization and never fills node-backed storage.

## Operator configuration

Recommendation-only child-chart example:

```yaml
metricsCA:
  configMapName: metrics-serving-ca
  key: service-ca.crt
rbac:
  profile: read-only
agentConfig:
  scope:
    include_namespaces: [my-application]
  storage:
    enabled: true
    mode: recommendation
    threshold_percent: 85
    growth_percent: 15
    sustain_seconds: 300
    allowed_storage_classes: [my-expandable-csi]
    metrics:
      url: https://my-prometheus.example
      cluster_label: cluster
      cluster_value: my-cluster
      ca_file: /etc/sre-autoheal/metrics-ca/ca.crt
      token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
```

The metrics server must separately authorize the service account. Do not embed
credentials in URLs. Omit metricsCA/ca_file for a system-trusted CA. HTTP is only
explicitly allowed for isolated credential-free fixtures. Custom CA mounting is
read-only; no metrics-server permissions are silently granted.
The configured cluster label/value must be present on returned volume metrics.
All four queries must have identical source labels, excluding the metric name;
foreign-cluster data and cross-node joins fail closed.

For automatic mode also configure `storage.mode: automatic`, exact
`storage.targets: [{namespace: my-application, name: exact-pvc}]`, and label the
PVC `sre-autoheal.nvidia.com/storage=true`. Global `policy.mode` must be `safe` or
`assisted`, without pause/dry-run. ConfigMap memory or persistent file memory is
required. Existing `managed=false` opt-out overrides storage opt-in. Keep generic
`rbac.profile: read-only` for storage-only mutation.

The automatic profile supports Bound Filesystem/RWO PVCs, expansion-enabled
allowlisted StorageClasses, available quota, one expansion per cycle and a hard
2Ti cap. Pending/failed operations cannot be resized again automatically.

KubeVirt uses guest filesystem telemetry, not host disk.img utilization. Running,
Ready, AgentConnected and exact PVC-to-device mapping are required. This phase
never runs SSH, growpart/resize2fs, VM stop/start or reboots. Expanded PVCs with
still-high guest usage report `guest_growth_needed` and lock further PVC growth
until human reconciliation. No universal 0.9234 overhead factor is assumed.
Guest collection time is not proof of guest-agent source freshness. Untimestamped
guest responses can inform investigation but cannot establish healed recovery.

CSI allocation rounding is opt-in via `storage.capacity_rounding` per approved
StorageClass, at most 1Gi. The default does not relax the capacity-identity bound.
The OCP fixture explicitly declares the observed 1Gi allocation unit: a request
of 1178Mi produced a filesystem of 2,077,073,408 bytes. This exception is only a
bounded size-consistency allowance, not proof of metric identity; cluster and
source-label checks remain mandatory.

## Review rulings and remaining boundaries

- Independent read-only review identified six Important findings; regression
  fixes cover pending capacity identity, observation gaps/inventory failures,
  query source identity, untimestamped guest recovery, revoked completion gates,
  and the chart-wide RBAC switch.
- Ruling: allow explicitly configured CSI allocation rounding, never silent
  heuristic relaxation. Cost if configured incorrectly: a filesystem smaller
  than the permitted rounding ceiling could evade the size consistency check;
  authenticated source identity and exact targeting remain independent gates.
- Ruling: guest telemetry cannot prove recovery without source freshness;
  report partial/needs-human-review, rather than certify stale data as healed.
  Cost: more manual guest verification even when a disk may already have grown.
- Deferred minor: storage currently requires explicit scope of at most 20
  namespaces. Wildcard/large-scope enumeration needs its own integration test.
- Review deliberately excluded parent Helm Git source integration, CSI-driver
  internals, production multiprocess persistence, external Slack/SMTP delivery
  and guest command execution. Tests here cover child-controller deployment and
  namespace-local SMTP; no broader production-ready claim is made.

## Recovery and validation

- Inspect exact PVC UID, requested/reported sizes, events and annotation
  `sre-autoheal.nvidia.com/storage-expansion` before any recovery.
- Submission errors are uncertain, not permission to re-patch. A timeout does
  not cancel CSI resize. Never clear operation locks during an active resize or
  attempt to shrink PVCs. Preserve/export incident memory before reconciliation.
- Failed-submission state and failed/pending operation annotations need explicit
  human reconciliation. Agent restart alone must not unlock another expansion.
- Fixtures use namespace `sre-storage-validation-20261005`, PVC
  `validation-data`, releases `sre-storage-ocp` / `sre-storage-k8s`. SMTP messages
  stay inside the namespace and must contain zero attachments.
- `/fill` refuses synthetic telemetry, filesystem capacity above 2Gi and writes
  above 1Gi. The normal sustain window remains 300 seconds.
- Native `local-path` has expansion disabled. Safe rejection is not evidence of
  successful native CSI resize; publication remains blocked on that live test.
- Existing Hermes/CoCo releases and their PVCs remain outside validation scope.

## Final validation evidence — October 5, 2026

- Full recipe suite: 112 tests passed; child-chart Helm lint passed. Source remains uncommitted.
- OpenShift release `sre-storage-ocp`, revision 4, deployed in the isolated namespace.
  Earlier automatic revision 3 performed the actual resize: request/capacity
  `1Gi -> 1178Mi`, CSI `FileSystemResizeSuccessful`, mounted filesystem usage
  `43.2447%`. The final reviewed revision 4 passed a **read-only recovery replay**
  against that actual resized PVC; it did not submit a second resize. Captured
  recovery email contained zero attachments.
- Fixture rollout was changed to `Recreate`: its RWO PVC prevented the replacement
  pod from starting while the old metrics server remained mounted. Updated metrics
  include the required cluster/source labels; the controller rejected the stale
  unlabeled fixture before it was replaced.
- Native Kubernetes release `sre-storage-k8s`, revision 3, deployed successfully.
  Its only StorageClass is `local-path` (`rancher.io/local-path`) with expansion
  unset. Persisted automatic outcome: `blocked`, reason `StorageClass does not
  allow volume expansion`, target `1178Mi`, request/capacity still `1Gi`, no
  expansion annotation. Utilization is explicitly synthetic 88%, not real disk
  pressure. Exact-PVC patch RBAC passed; unrelated-PVC patch RBAC denied.
- Native persisted email delivery succeeded. After refreshing the fixture (which
  clears its in-memory mailbox), a notification-only replay to the local SMTP
  catcher succeeded with zero attachments; no Kubernetes or durable-memory write.
- Publication gate is **not satisfied**: no successful native CSI resize, no live
  KubeVirt guest-growth validation, no external email/Slack delivery test. No commit,
  push, or update to upstream PR 197 was made. Need an approved expansion-capable
  native Kubernetes StorageClass before completing the requested resize validation.
- Actual KubeVirt guest mutation is not implemented in this phase. The controller
  identifies guest-growth needs and escalates; it never executes guest commands,
  stops a VM, or certifies recovery from untimestamped guest telemetry.
- Isolated releases/fixtures are retained for follow-up; automatic mode targets
  only the disposable `validation-data` PVC. Existing production releases unchanged.

## PVC-only admin/owner follow-up update — October 5, 2026

- Fetched origin and NVIDIA main before edits; safely fast-forwarded
  `aguda/nemoclaw-kubernetes` to `b7396d1cc8c4b36aab64227f4903b5c2fd3a157e`.
  Local committed HEAD equals the fetched origin branch. Fetched NVIDIA main
  `94c9eae154aefc486af8ef6cacb532a8e37031ec` is an ancestor; no rebase or
  force-push. Upstream PR remains #197. These new changes are uncommitted.
- A fresh local backup was retained for the guest follow-up update.
  Existing storage work, unrelated ledger_rag mode change and Hermes CoCo
  testing worktree were preserved.
- Added deterministic human-only admin/VM-owner instructions. Emails identify
  VM/PVC and observed device/mount/filesystem. Admin verifies attachment and
  backup/snapshot, then shares an approved guest procedure with the owner.
- Conditional ext4/XFS simple-partition examples are supplied only after
  verified PVC expansion and a current mapping. Unknown/historical/reassigned
  mappings require inspection. Failed/unverified expansion explicitly says not
  to grow the guest yet. No SSH, guest executor, DataVolume patch or reboot.
- Operation annotations retain VM identity across restarts/guest-agent outages,
  including completion of older operations lacking cached context. Manual
  follow-up keeps observing usage without submitting another expansion.
  Untimestamped guest responses remain unverified, even below threshold.
- Fresh local validation: 124 recipe tests passed in an isolated copy (including
  47 storage behavioral tests); 74 repository Python tests and 14 Node tests
  passed. Catalog tests initially failed for missing pinned dependencies; all
  passed after installing the existing hash-pinned requirements in a temporary
  virtual environment. Helm lint, SPDX check (972 files) and git diff --check
  passed. Expected fault-injection logs are exercised by the storage tests.
- These follow-up changes have not been deployed or live-tested. No external
  admin email was sent; MIME tests exercised the real EmailSink with fake SMTP
  transport and verified zero attachments. Earlier live evidence above applies
  to the prior implementation only. No commit, push or PR mutation; successful
  native CSI expansion remains the publication gate.
