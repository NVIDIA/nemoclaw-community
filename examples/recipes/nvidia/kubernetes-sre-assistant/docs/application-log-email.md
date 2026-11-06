<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Application logs in escalation emails

The auto-heal controller collects container logs for workload findings and includes
bounded excerpts in escalation emails. It tries current or previous logs according
to the finding and falls back to the other path if the requested logs are unavailable.
No separate privileged log-reader service is required.

Emails include at most the last 50 collected lines, capped at 12,000 characters.
The controller redacts known credential patterns before rendering the excerpt.
If collection fails, the message states that logs are unavailable. Logs appear
inline; the message has no raw incident JSON or log attachment.

## HTTP content negotiation

Pod-log GET requests use `Accept: */*`. The HTTP transport keeps the response as
raw text, including JSON-lines output. Resource API requests continue to use
`Accept: application/json` and parse resource responses separately.

Some Kubernetes/OpenShift API servers reject `Accept: text/plain` with HTTP 406
during serializer negotiation, before streaming Pod logs. Changing the Accept
header fixes that negotiation failure. HTTP 403 still requires an authorization
check; changing the header does not grant permission.

## Required permissions

Role-based access control (RBAC) requires `get` on the core `pods/log` subresource.
The `previous=true` query uses the same permission. The chart declares this rule
separately from the `get`, `list`, and `watch` rules used for resource discovery.
All three built-in profiles (`read-only`, `safe`, and `safe+nodes`) use this
GET-only log rule. The change adds no Secret-read or Pod-exec permission.

The chart creates a ClusterRole and ClusterRoleBinding, so its log permission
applies across namespaces. Detector namespace filters do not narrow RBAC. For
namespace-bound log access, an administrator must replace the broad log grant
with Roles and RoleBindings for the selected namespaces; adding a RoleBinding
alone does not restrict an existing ClusterRoleBinding.

## Configure and verify delivery

Configure the existing email sink through `notify.email.enabled`, SMTP host and
port, `to_addrs`, sender, and allowed recipient domains. Use existing Secret
references when SMTP credentials are required. Preserve the operator's recipient
configuration and keep credentials out of source control.

Replace the uppercase placeholders with your namespace, workload, container, and
service-account names. An administrator can run these checks:

```sh
kubectl auth can-i get pods/log -n APP_NAMESPACE \
  --as=system:serviceaccount:SRE_NAMESPACE:SRE_SERVICE_ACCOUNT
kubectl logs deployment/SRE_DEPLOYMENT -n SRE_NAMESPACE -c agent --tail=100
kubectl logs APP_POD -n APP_NAMESPACE -c APP_CONTAINER --tail=50
kubectl logs APP_POD -n APP_NAMESPACE -c APP_CONTAINER --previous --tail=50
```

The permission check must return `yes` for the controller's service account.
Administrator log access alone does not verify collection through the controller's
HTTP transport. Check the controller's notification result and the received email
for a unique application-log marker.

SMTP success means that the mail server accepted the message. Confirm inbox
receipt separately. Previous logs require a restarted container and may become
unavailable after the runtime removes that container's logs.

## Validation and deployment

From the repository root, run the transport and rendered-RBAC regression checks:

```sh
python3 -m unittest discover \
  -s examples/recipes/nvidia/kubernetes-sre-assistant/tests \
  -p test_autoheal_resilience.py -q
```

The tests exercise current and previous log requests, preserve raw log text,
and verify GET-only `pods/log` access without Secret reads or Pod exec in each
built-in profile. They do not contact a live cluster or send email.

A separate OpenShift smoke test on October 14, 2026 created one CPU-only,
intentionally crashing workload. The controller sent an escalation, and inbox
inspection confirmed the log marker, traceback, and exit code 42 inline. Previous
container logs were unavailable for that Pod. The test namespace and workload
were removed after verification. This validates the exercised notification path;
it does not establish delivery for other SMTP configurations or live installation
of the revised GET-only RBAC template.

Package the recipe from the updated chart source. If another release vendors this
subchart, synchronize its copy before packaging. A later Helm upgrade from older
source can overwrite a targeted live ConfigMap repair. Use the release that owns
the existing resources when upgrading.
