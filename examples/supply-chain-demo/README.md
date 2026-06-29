# Nemoclaw Supply Chain Demo

This demo will provision Nemoclaws to participants via a unique URL. Participants will be able to interact with their own Nemoclaw live, without any additional setup. Participants will walk through a guided use case and use Nemoclaw to assist them in answering supply chain related questions.

## Workshop Agenda
1. [20 min] Introduce participants to Nemoclaw and Openshell using slidedecks from Highspot: [Nemoclaw](https://nvidia.highspot.com/items/69b86365d08c0af085ad7596?lfrm=srp.0#1), [Openshell](https://nvidia.highspot.com/items/69b843cc5be327c099292acb?lfrm=srp.0#1)
2. [40 min] Start the hands-on workshop section
   - Distribute unique URLs to each participant so they have their own Nemoclaw instance. (Note that you will *not* need to give participants access to a Brev launchable, they only need the URL. See below for how to set this up.)
   - Give participants the `instructions.html` page (included in this repo). This page is the main landing spot for the workshop. Talk through these instructions and have them follow along. This page has been hosted as a Github Page for convenience: [https://katherineh123.github.io/nemoclaw-demo/instructions.html](https://katherineh123.github.io/nemoclaw-demo/instructions.html)
   - The instructions page will introduce concepts such as a corporate **knowledge base** and **enterprise data**. Participants will be able to gain a hands on understanding of these concepts by interacting with the `enterprise-knowledge-base.md` and `factory-delivery-data.csv` artifacts (included in this repo). **Give participants the links to these artifacts** so they can see the artifacts in their raw form. The instructions page provides a series of sample prompts for participants to try, which will demonstrate Nemoclaw automatically pulling in the artifacts and using them to solve real problems.

See the **How to Set Up the Workshop** section below for guidance on how to provision a Brev VM and set up the workshop.


## How to Set Up the Workshop
If you are setting up this workshop for participants *other than yourself*, read all 6 steps first before starting to execute them. This is so you can understand the access permission sensitivities involved in this demo: all demo participants will have **write access** to the GitHub repo hosting the demo. To avoid risk to your Github account, consider creating a new account for the demo.

**Also note: you must use either MacOS or Linux to host the workshop.** Workshop *participants* can use any OS.

1. **Fork the repo** — fork the repo [https://github.com/katherineh123/nemoclaw-demo](https://github.com/katherineh123/nemoclaw-demo/tree/main).
2. **Update the repo link in the instructions** — in `enterprise-knowledge-base.md` and in the Prompt 1 text inside `instructions.html`, replace the repo URL with your fork's URL.
3. **Create a Brev instance** — provision a instance with 48 CPUs and 192 GiB RAM. (This is enough for 15 participants to run concurrent openclaws, you can adjust resources up or down for your use case). Follow the brev commands on the brev launch page to ssh into your VM.
4. **Run the setup script** — Clone the repo inside of your brev instance, and then run the setup script (`sudo bash setup_exec_demo.sh`). It provisions N isolated OpenShell sandboxes, each with NemoClaw inside.
   The script pins NemoClaw to `v0.0.35` by default so upstream NemoClaw releases do not affect the demo.
5. **Enter credentials when prompted** — the script will ask for:
   - NVIDIA `build.nvidia.com` API key. This key grants access to an LLM. To get a key, create an account at build.nvidia.com, navigate to any model such as [this](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b) one, click "View Code" (top right) > "Generate API Key".
   - Brave Search API key. Create a key at brave.com. Brave grants $5 of free credits.
   - GitHub Personal Access Token (PAT) of the Github account that the forked repo resides in
   - URL of the forked repo
   - OpenClaw URL mode: `custom-domain` for a Cloudflare named tunnel on your own domain, or `quick-tunnel` for random `trycloudflare.com` URLs. Suggest to try with quick-tunnel first because it requires no additional setup.
   - Cloudflare domain name, if you choose `custom-domain`
6. **Important note on GitHub access** — **demo participants will have write access to the GitHub repo via the PAT. To avoid risk to your main account, consider creating a dedicated account for the demo.**



## Secrets

The NemoClaw demo setup script caches values on the VM for convenience.

Secret values (NVIDIA inference.nvidia.com key, Brave key, and GitHub PAT) are stored in **plaintext on the VM** at:

```text
~/.nemoclaw/exec-demo/secrets.tsv
```

Non-secret setup values like the Github fork's URL are cached separately on the VM at:

```text
~/.nemoclaw/exec-demo/env.tsv
```

Note that the cached secrets file is NOT directly readable by the OpenClaws. During demo
startup, the setup script reads the saved values on the VM and injects the
credentials through [OpenShell's](https://github.com/NVIDIA/OpenShell) provider/credential flow.


## Demo files

| File | Purpose |
|------|---------|
| `factory-delivery-data.csv` | 24 months of monthly headcount and on-time delivery data for two factories (Germany / Asia). This is the raw data the agent pulls and analyzes. |
| `enterprise-knowledge-base.md` | Company knowledge base / skill document. Describes the factories, performance thresholds, forecasting methodology, and publishing standards - all in plain language. The agent reads this before starting work to understand the business context. |
| `instructions.html` | Step-by-step demo guide for participants. Explains NemoClaw, data connectors, and walks through all four prompts with "what to expect" notes. |
| `setup_exec_demo.sh` | Fresh-VM setup/reset script for the NemoClaw demo. It installs dependencies, prompts for credentials, creates isolated OpenClaw sandboxes, and prints each demo participant's links. |

## Troubleshooting
- **LLM Rate Limiting 429 errors:** the build.nvidia.com endpoint may throw 429 errors if too many participants access the endpoint at once. Errors should be intermittent and resolve on retry.
- **Nemoclaw / Openshell version update errors:** Nemoclaw and Openshell are both early projects which a fast release cadence. New releases may break the demo script. Please reach out for questions/help if this is the case.
