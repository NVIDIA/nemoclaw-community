# Adapting FinGuard for Production FSI Environments

FinGuard is a reference control pattern, not a production payment product. Its
most reusable feature is the separation between an agent that prepares a
decision and a human-controlled system that executes it.

## What partners can reuse

| Component | Reusable pattern |
|---|---|
| Derived Hermes image | Layer domain skills and native NeMo Relay configuration on a pinned NemoClaw base. |
| OpenShell policy | Start deny-by-default and grant only named inference, data, and observability paths. |
| FinGuard skills | Keep screening, explanation, evidence preparation, and boundary testing as distinct capabilities. |
| Maker/checker workflow | Let the agent prepare a recommendation while a separately authenticated human owns release. |
| NeMo Relay and ATIF | Capture agent turns and tool activity as portable execution evidence. |
| Phoenix/OpenInference | Separate agent telemetry from host-side human control-plane audit events. |
| Phased scripts | Make infrastructure, provider, sandbox, and demo-service setup independently testable. |

## What partners should replace

| Example component | Production integration |
|---|---|
| Synthetic JSON payment queue | Payment hub, workflow engine, or ISO 20022 message source exposed through an approved read interface. |
| Curated OFAC fixture | Maintained sanctions-screening service with list provenance, version, matching policy, and audit history. |
| Static limit and validation rules | Enterprise policy/rules engine with controlled versions and change approval. |
| Fixture duplicate and beneficiary checks | Bank systems of record, fraud services, beneficiary validation, and account controls. |
| Mock payment rail | Existing payment execution platform outside the agent sandbox. |
| `Jane Ops` demo identity | Enterprise identity, strong authentication, entitlements, and approval workflow. |
| Local Phoenix | Approved observability platform, evidence archive, or SIEM with retention and access controls. |

The included OFAC data demonstrates a screening input. It is not a substitute
for a production sanctions product. A partner can connect its existing vendor
or internal screening service by exposing a narrow tool contract to the agent,
for example `screen_party` or `get_screening_case`. The tool should return the
decision, matched-list provenance, score or rationale, policy version, and case
identifier without granting list administration or disposition authority.

## Scoping partner network access

`allowed_ips` is optional and environment-specific. This example does not need
it for the exact `host.openshell.internal` Phoenix endpoint. A partner may add
it when an approved hostname resolves to controlled private infrastructure or
when institutional policy requires destination IP pinning. The network or
service owner should supply the range.

Use the smallest stable range possible, preferably a single `/32` IPv4 or
`/128` IPv6 address or a narrowly scoped service subnet. Do not copy broad
private ranges such as `10.0.0.0/8` or `172.16.0.0/12` into a production policy:
they could let the approved hostname resolve to unrelated internal systems.
Also avoid `172.0.0.0/12`, which includes public addresses.

For example, a partner-owned screening endpoint could be scoped as follows:

```yaml
network_policies:
  partner-screening:
    name: partner-screening
    endpoints:
      - host: screening.fsi-partner.internal
        port: 443
        protocol: rest
        tls: terminate
        enforcement: enforce
        allowed_ips:
          - 10.42.18.25/32
        rules:
          - allow: { method: POST, path: "/api/v1/screen" }
    binaries:
      - { path: /usr/bin/python3 }
```

The IP range complements rather than replaces restrictions on hostname, port,
HTTP method and path, and calling binary. Load-balanced services may require a
vendor-published CIDR and a reviewed update process for address changes. Record
the service owner, business purpose, approved range, and review date; inject
credentials through an OpenShell provider rather than storing them in policy.
The payment-execution rail must remain absent.

## Controls that must remain invariant

- Never give the agent payment release, settlement, override, or sanctions-case
  closure credentials.
- Keep payment execution outside the agent sandbox and outside its network
  allowlist.
- Require a distinct authenticated human or approved deterministic workflow
  for final release.
- Revalidate material payment and screening data at approval time; do not rely
  only on an earlier agent response.
- Record who or what performed each action. Agent, automated control, and human
  events must not share an ambiguous identity.
- Preserve input provenance, control versions, tool results, exceptions, and
  the final disposition for audit and replay.
- Apply data minimization, encryption, retention, regional handling, and access
  controls required by the deploying institution.

## Recommended tool boundary

Tools made available to the sandbox should be read-oriented or
recommendation-oriented:

| Tool capability | Agent access | Reason |
|---|---:|---|
| Read payment details and status | Allow, scoped | Required to screen and explain. |
| Run sanctions, duplicate, fraud, or beneficiary checks | Allow, scoped | Produces evidence without executing value transfer. |
| Create or append a compliance case | Allow with validation | Supports escalation while preserving reviewer authority. |
| Read policy and control versions | Allow | Makes recommendations reproducible. |
| Prepare a release packet | Allow | Produces a human-review artifact only. |
| Close a compliance case or override a hold | Deny | Must remain with an authorized reviewer or controlled system. |
| Release, settle, cancel, or reroute funds | Deny | Violates the maker/checker boundary. |

A useful next extension to this example is a mock compliance case-management
API. FinGuard could create a case and append evidence, while OpenShell policy
and the API's own authorization both prevent the agent from closing the case or
overriding a hold. That makes the regulated workflow more realistic without
weakening the payment-rail boundary.

## Suggested adoption sequence

1. Reproduce this example unchanged and preserve its ATIF and Phoenix evidence.
2. Connect one read-only non-production data service through a narrow,
   authenticated tool contract.
3. Map every tool to an owner, data classification, policy rule, and expected
   trace before enabling it.
4. Replace the host checker with the institution's authenticated approval
   workflow while keeping execution unreachable from the sandbox.
5. Validate denied paths, stale-data handling, retries, idempotency, identity
   attribution, and evidence retention with risk and compliance stakeholders.
6. Promote only after model, tool, policy, and control versions can be audited
   together.

FinGuard's value is not a particular screening algorithm. It is the visible,
testable boundary between agent assistance, deterministic controls, human
accountability, and payment execution.
