<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Encrypted storage is a prerequisite for the connectors

The fixture path stores invented messages and needs nothing from you. A
connector changes that: once one is attached, the store holds real subjects,
senders and message bodies, and the memory holds what was inferred from them.

**Before attaching a connector, the profile home must sit on an encrypted
volume.** `scripts/setup-slack.sh` checks what it can and asks you to confirm
the rest; this page is what it is asking about.

## Owner-only permissions are not encryption

The store is created `0600` inside a directory created `0700`, and the
capability cache is written the same way. That stops another account on a
running system reading the file. It does nothing at all for:

- a laptop that is lost or stolen
- a disk that is imaged, resold, or returned under warranty
- a backup taken at the block or file level
- a snapshot of the volume the sandbox's storage lives on

Those are the cases encryption at rest addresses, and permissions do not
overlap with any of them. The two protect different things and the recipe
needs both.

## Which volume this is about

Not the path inside the sandbox. `HERMES_HOME` there is an overlay filesystem
with no block device behind it — encryption is not merely unconfigured from
inside a sandbox, it is unobservable, and a check run in there would be
answering a different question.

What protects the store is the host volume underneath the sandbox's storage,
and **where that is depends on the driver**. Docker keeps it under its
data-root, a VM keeps it inside a disk image, Kubernetes in a volume. None of
those is reliably the host's home directory, so `setup-slack.sh` does not
guess: it requires `SANDBOX_STORAGE_PATH` and verifies that path.

Find it for the Docker driver with:

```bash
docker info --format '{{.DockerRootDir}}'
```

Then:

```bash
SANDBOX_STORAGE_PATH=<path> bash scripts/setup-slack.sh
```

## Verifying it

**Linux, LUKS/dm-crypt.** Find the device behind the path and ask what type it
is:

```bash
findmnt -no SOURCE --target "$HOME"
lsblk -no NAME,TYPE $(findmnt -no SOURCE --target "$HOME")
```

A `crypt` in the `TYPE` column means the volume is encrypted. A bare `part` or
`lvm` with no `crypt` above it means it is not.

```bash
# Or, directly:
sudo cryptsetup status $(basename $(findmnt -no SOURCE --target "$HOME"))
```

**macOS, FileVault.** The host of a NemoClaw sandbox is Linux, so this applies
to a plain Hermes install rather than the sandboxed path:

```bash
fdesetup status
```

`FileVault is On.` is the answer you want.

**Cloud instances.** Encrypted-by-default root volumes are common but not
universal. On EC2 check the volume's `Encrypted` attribute; on GCE persistent
disks are encrypted at rest by default; on Azure check the disk's encryption
settings. Being on a managed platform is not by itself an answer.

## If it is not encrypted

Two honest options.

**Move the storage.** Put the sandbox's storage — or, for a plain Hermes
install, `HERMES_HOME` — on a volume you have encrypted. On Linux that is a
LUKS container; the profile home can be a directory inside it.

**Do not attach a connector.** The fixture path, the walkthrough and the whole
test suite work without one and store nothing real. The recipe is still worth
running that way; it simply judges a synthetic corpus instead of your mail.

What the recipe will not do is pretend the question was answered.
`setup-slack.sh` refuses to attach a provider until you confirm, and
`STORE_ENCRYPTION_ACKNOWLEDGED=1` exists for unattended installs where you have
already established this — it records that you took the decision, not that the
decision was made for you.

## What this does not cover

Encryption at rest protects the disk. It does not protect a running system, and
it is unrelated to credential custody: the Slack credential is held by the
OpenShell gateway and never written into the store at all. Those are separate
requirements and neither substitutes for the other.

Application-level encryption of the message bodies — encrypting the store's
contents rather than the volume under it — is the other way to satisfy this,
and it is not what this recipe does today. It would need a key-management
design, and that is a larger proposal than a prerequisite.
