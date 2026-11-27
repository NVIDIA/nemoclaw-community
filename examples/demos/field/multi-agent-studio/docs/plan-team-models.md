# Open Task team and model selection

**03 Open Task** starts with Casey as coordinator. Send `/goal` to assign up to three specialists. `/plan` and `/plans` remain aliases. Leave out the command for a direct conversation.

## Choose a team

- **Hired only** (default): Casey uses your available hires. At least one is needed, and specialist assignments require relevant equipped skills. No particular role preset is required.
- **Hired + Standby**: Casey first assigns an available hire whose equipped skill matches the work. A matching hire takes priority over the equivalent standby specialist. Casey calls Scout (research), Cody (programming), Ada (analysis), Iris (design) or Vera (review) only when no matching unassigned hire is available, or when you explicitly request that standby specialist. This mode also works without hires. The **OpenShell in action** example names **Shell**, an opt-in protected standby researcher, and selects Hired + Standby.

Assignments use the actual tools and permissions of the selected agent. A substantial assignment must match the hire’s equipped skills. Naming an unsuitable hire does not force participation: Casey explains the missing expertise instead. Tool access alone is not suitability, and a skill does not bypass OpenShell policy. Independent review requires a different agent from the producer. Casey’s chat and Mission Control show **Why this agent** from the saved plan; **Not assigned** explains declined named participants. Speech bubbles remain short. Earlier plans may have no recorded selection reason.

Idle hires follow you into Open Task and wait on benches. Assigned agents move to workbenches and stay there after completion; the next confirmed plan moves replaced agents back to waiting seats. The selected mode is locked during a task. Changing modes afterward retains results; reload and Reset Open Task default new tasks to Hired only. Reset clears scenario results and restores standby default models, while preserving hired agents, their model choices and their own files.


## Choose models

1. Configure Local and/or External Endpoint in **Settings → Model**. Select the **Open Task** connection.
2. Local hires automatically use the External Endpoint default in Open Task when available. Explicit hiring API choices stay unchanged. Select an idle hire's model badge to override its Open Task model (including Local), or choose **Automatic** to restore this rule. Returning to Lounge uses the original hiring choice. Active or reserved hires cannot change models.
3. To change an individual standby model on an external NVIDIA connection, select **Hired + Standby** and expand **Standby specialists**. Choices save immediately for future work. Return to Hired only before starting if that is your intended team.

Casey starts with the Open Task default. On an NVIDIA connection, click Casey’s model beside the name or in **Standby specialists** to pick a fixed model. Choose **Use Open Task default** to follow Settings again. When following **Model routing (NeMo Switchyard)**, Casey calls the configured **Capable** model directly. Standby specialists inherit the connection default and can have individual NVIDIA model choices. Changing the Settings default affects inherited choices only. The selected Local connection remains available when needed.

**Models & connection** opens the shared Settings panel. Team model choices are locked while work or a reset is in progress.

See [model settings](runtime-settings.md) and [credential storage](session-credentials.md).

All Hiring presets, including Data analyst, use connected Local first, otherwise the configured External Endpoint default (**Model routing (NeMo Switchyard)** on eligible NVIDIA connections). Roles and skills do not override that default. Choosing a model manually or editing an existing agent preserves that choice.

## Switchyard

**Model routing (NeMo Switchyard)** defaults to Nemotron 3.5 Lightning for Router and Efficient, with Nemotron 3.5 Super VL for Capable. In Settings, select each role from the NVIDIA catalog, then click **Use model**. The studio matches each role to the model ID advertised by the connected NIM endpoint. Each eligible NVIDIA endpoint starts with Switchyard. Selecting a fixed model changes the default for that endpoint only. OpenAI and Anthropic use the model you select directly. Custom combinations show a short untested-configuration notice; Use defaults restores the tested baseline. Changes require idle agents and apply to new requests. Fixed model choices remain fixed.

Image-bearing conversations bypass the classifier and use an image-capable answer model. Capable is preferred when both support images; otherwise Efficient is used. Missing capability metadata is checked with a small synthetic-image request and cached for 15 minutes per endpoint, credential and model. This may add a short wait on the first image request. If neither model supports images, or support cannot be verified, the app explains the limitation instead of dropping the image. This input check does not certify answer quality or tool use.

Settings shows all three roles. Reply badges and Mission Control identify models recorded for that response or step; absent telemetry is left blank rather than inferred from the current selection. A routing choice without a completed response is labelled **Selected**.
