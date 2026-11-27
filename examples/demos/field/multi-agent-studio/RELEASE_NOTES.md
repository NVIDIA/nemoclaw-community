# Release notes

## Summary

Multi-Agent Studio is an interactive demo of AI agents working as a team.
Hire agents, chat with them in Agent Lounge, and give them a shared task in
Open Task. Follow assignments, specialist handoffs, tool activity, and results
in the studio, with local or external models and explicit website-access approvals.

```text
[Your task] -> [Casey] -> [o_o] [o_o] [o_o] -> [Results]
```

## Version 1.0.0

### Highlights

- Settings adds agent connection controls for Local and External Endpoint models, including per-endpoint NVIDIA NeMo Switchyard role selection for eligible NVIDIA endpoints.
- NVIDIA NeMo Switchyard routing is surfaced in the demo: eligible NVIDIA requests can route between Efficient and Capable models, and Mission Control/reply badges show the recorded model choice.
- Open Task adds user-facing model controls for Casey and idle hires, with standby specialist model overrides available on external NVIDIA connections in Hired + Standby mode.
- OpenShell-protected Open Task research now supports explicit policy review and continuation: viewers can open policy from the permission bubble, approve website access, and see the task resume with access history preserved.
- Weather-skilled Lounge agents can answer simple forecasts using MET Norway data with offline city lookup, showing the resolved city and source for grounded forecast replies.

## Version 0.3.0

### Highlights

- Updates the demo to OpenClaw 2026.11.3 and aligned plugins, with support for OpenShell-managed sandbox lifecycles.
- Adds a portable installation kit with a versioned runtime image and application files.
- Includes the application version and release notes in downloadable builds and installation kits.

## Version 0.2.4

### Highlights

- Review OpenShell website-access requests in Open Task, with the blocked agent named and access evidence available before choosing Continue.
- Resume protected research with the same specialist, preserving its assignment and access history while reducing repeated attempts and duplicate output.
- Follow permission requests and continuations chronologically in Mission Control, with clearer prompts from Casey when review is needed.
- Reset Open Task to clear saved Shell website approvals.
- View the current application version and release notes in Settings About.
