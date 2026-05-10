![NVIDIA](../../assets/nvidia_header.png)

# Phoenix And NemoFlow

This demo configures OpenClaw sub-agents. It does not use the Hermes NemoFlow
patch path.

`extras/docker-compose.yml` still provides Phoenix as a common observability
target across examples:

```bash
bash scripts/00-host-services.sh
```

Phoenix will be available at `http://localhost:6006`.

When using a NemoFlow-enabled OpenClaw runtime, set:

```bash
NEMO_FLOW_PROJECT_NAME=openclaw-omni-demo
PHOENIX_COLLECTOR_ENDPOINT=http://172.17.0.1:6006/v1/traces
```

Phoenix groups OpenInference traces by the `openinference.project.name`
resource attribute, so the OpenClaw NemoFlow plugin should set
`telemetry.openInference.resourceAttributes.openinference.project.name` to the
same value.

NeMo-Flow 0.1.0 ships an OpenClaw patch that adds a `nemo-flow` plugin with
OpenInference telemetry fields (`serviceName`, `instrumentationScope`,
`resourceAttributes`, and related settings). A plain already-onboarded
NemoClaw/OpenClaw sandbox may not include that patched plugin, so this demo
does not require traces to pass. The primary verification path is
`scripts/verify.sh`, which checks provider auth, direct vision, and main-agent
delegation.
