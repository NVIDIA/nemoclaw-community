<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# GitHub Policy

The assistant uses GitHub's REST API through OpenClaw's Node.js runtime and
`curl`. The recipe therefore installs a dedicated policy instead of relying on
a Git-oriented preset whose executable allowlist may not include those tools.

Apply [`../../../policies/github-api.yaml`](../../../policies/github-api.yaml)
with the recipe's installer:

```bash
bash scripts/install.sh
```

The rule grants only:

- `api.github.com:443`
- inspected REST traffic
- `GET`
- `/repos/**`
- the OpenClaw, Node.js, and curl binaries used by the runtime

The assistant can read public pull requests. It cannot comment, label, merge,
or close one because no GitHub write method is granted.

If a request is denied, inspect the host, method, path, and executable in
`openshell term`. A `CONNECT tunnel failed` response comes from the policy
gate. A GitHub rate-limit response contains a JSON body returned by GitHub.

Do not broaden the rule to all methods and do not copy a personal GitHub token
into the sandbox. See [failure-modes.md](failure-modes.md).
