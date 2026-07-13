# Getting Started on Brev

## 1. Prepare the VM

The example expects Docker and OpenShell. It does not require a Python virtual
environment.

If OpenShell is not already installed, install the pinned version used by this
example:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh \
  | OPENSHELL_VERSION=v0.0.53 sh
```

```bash
docker info >/dev/null
openshell --version
systemctl --user status openshell-gateway --no-pager
```

Enable provider v2 once per gateway:

```bash
openshell settings set --global \
  --key providers_v2_enabled --value true --yes
```

## 2. Configure

```bash
cd ~/payment-ops-hermes-test
cp .env.example .env
nano .env
```

Set `COMPATIBLE_API_KEY`. The endpoint, model, sandbox name, Phoenix endpoint,
and project name have working defaults.

## 3. Bring up

```bash
bash scripts/bring-up.sh
```

The first image build can take several minutes. Do not interrupt it while
OpenShell is downloading the base image or building Hermes.

Bring-up keeps fixture validation concise. Run the detailed, offline control
smoke test separately whenever you want to inspect all six expected decisions:

```bash
python3 scripts/smoke-payment.py
```

The same command resumes the example after reconnecting to the VM. It reuses a
healthy `Ready` sandbox and restarts Phoenix, forwarding, and the demo
services. If `openshell sandbox list` instead reports terminal `Error`, replace
only the failed sandbox explicitly:

```bash
bash scripts/bring-up.sh --recover-error
```

This recovery uses cached image layers. A browser or SSH timeout by itself does
not require sandbox replacement.

## 4. Verify

```bash
bash scripts/verify.sh
```

Expose Brev HTTP ports `8800` and `6006`, then open the FinGuard and Phoenix
URLs. Keep the mock rail on port `8780` private.

## 5. Exercise maker/checker

Use the UI to screen the queue and ask FinGuard to release `WIRE-1007`. The
sandbox policy must deny access to the payment rail.

Run the separate checker on the host:

```bash
python3 scripts/approve_release.py --id WIRE-1007 --approver "Jane Ops"
python3 scripts/approve_release.py --id ACH-2003 --approver "Jane Ops"
```

The first command releases a cleared fixture. The second refuses a held one.

## 6. Preserve traces and clean up

```bash
bash scripts/download-traces.sh
bash scripts/tear-down.sh
```

To remove all example state:

```bash
bash scripts/tear-down.sh --destroy-sandbox --purge-host-services
```
