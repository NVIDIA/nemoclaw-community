# Hermes

Creates a NemoClaw-managed Hermes sandbox on a fresh Brev CPU instance through a notebook.

| Catalog field | Value |
| --- | --- |
| Industry | ☁️ Cloud Services |
| Requirements | Linux Brev CPU instance · Docker · NVIDIA Build API key or compatible inference endpoint API key · billable Brev instance · best-effort support |
| Environment | Brev |

This example is a notebook for a [Brev launchable](https://brev.nvidia.com) to create a Hermes agent on a Brev CPU instance.

The notebook is the fastest path from a fresh Brev machine to a working NemoClaw-managed Hermes sandbox. The notebook installs the host prerequisites, prompts for an NVIDIA Build API key, runs Hermes onboarding, verifies the Hermes API, and shows how to open the Hermes TUI and OpenShell terminal.
