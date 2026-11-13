<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Auto Ontology (stage 4, work in progress)

Not installed by `scripts/install.sh` and not part of the skill. These files hold
what a spike verified so the next step can start from them.

- `provider-auto-ontology.yaml`: an OpenShell provider profile that binds an Auto
  Ontology API token to `host.openshell.internal:4000` and sends it as
  `x-api-key`, with three allowed paths. Lint passes.
- `ontology_qa.py`: the sandbox-side client (standard library): checks the
  semantic layer, asks for coverage, streams the text-to-SQL answer, and prints the
  SQL, rows and answer.

## What the spike showed (2026-11-13)

Verified from sandbox Python, with only a placeholder token in the sandbox:

- `GET /api/semantic-compilation/status` returned 200 through the profile's
  composed policy and `allowed_ips`.
- A path outside the profile (`/api/health`) was denied by the L7 policy.

Not verified: the chat (text-to-SQL) call. It timed out, from the sandbox and from
the host alike. The deployment's logs show why: its structured-output call to
the hosted `nemotron-3.5-bolt-e4b` model fails with HTTP 400 `unknown field
guided_json`. The hosted endpoint now rejects `nvext.guided_json` (400) while
top-level `guided_json` and `response_format: json_schema` both return 200, so
the Auto Ontology build deployed on 2026-11-05 (commit `cdaf61e1`) sends a request
shape the hosted API no longer accepts. The coverage endpoint still returned 200,
after about two minutes of retries.

## Next step

Move the Auto Ontology deployment to a build that sends an accepted shape, then
rerun the chat call from the sandbox. Then add `ontology_qa.py` to the skill with
rules that require reading the generated SQL, install the profile from
`install.sh`, and disclose that the deployment sends schema and question text to
hosted models using its own configuration.
