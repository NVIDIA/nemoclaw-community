# Running it on your own machine

The remote path puts the bots on a Linux host you SSH to. This one puts them on
the machine you're sitting at. Same `./swarm`, same sandboxes, same tests. The
difference is where the boundary sits: the bots are contained, but they're
contained on your laptop.

## What you need

macOS on Apple Silicon or Linux, with Docker. On a Mac that means Colima or
Docker Desktop; NemoClaw's install handles OpenShell either way.

```bash
brew install colima docker coreutils        # coreutils for `timeout`
colima start --cpu 6 --memory 14 --disk 60
```

Then install NemoClaw by following the
[NemoClaw quickstart](https://docs.nvidia.com/nemoclaw/); it installs OpenShell
with it and uses the Docker-driver gateway on a Mac, so there is no separate VM
helper to sign.

Hermes Desktop already bundles a 0.21 runtime, so `hermes` on the command line
is the only extra if you don't have it.

Memory matters more here than on a server. Each sandbox reserves
`SANDBOX_MEMORY`. With three bots on a 14 GB Colima VM, 3Gi each leaves room for
the image build and the collector. The defaults in `swarm.env.example` assume a
server; for a laptop set:

```bash
SANDBOX_MEMORY=3Gi
SANDBOX_CPU=2
```

## Bring it up

```bash
cp swarm.env.example swarm.env
$EDITOR swarm.env                    # model, endpoint, and the two lines above
umask 077; mkdir -p ~/.secrets
printf '%s' 'your-key' > ~/.secrets/inference.key
./swarm doctor                       # every check should pass before you build
./swarm up
```

First run is 8 to 12 minutes; the image build for arm64 is most of it. After
that, `./swarm up` is under a minute.

Then quit Hermes Desktop and open it again. The bots are under **This device**
in the Bots pane. There is no connection to add; they're on the machine Desktop
already manages.

## What's different from remote

Almost nothing in the tooling. `swarm` detects the bridge address by asking
Docker instead of reading a host interface, because on a Mac the bridge lives
inside the Colima VM. The Desktop hint at the end of `swarm up` says "quit and
reopen" instead of printing an SSH address. That's it.

What's different in practice:

Every bot's tools run on your laptop. They're sandboxed, with the same
namespaces and the same deny-by-default egress, but the machine underneath is
the one you type on. For a demonstration or to learn the shape, that's fine. For a bot
that holds credentials you care about, use a remote host.

Sleep pauses them. Close the lid and the sandboxes stop with the VM.
`colima start` and `./swarm up` bring them back.

The inference endpoint is probably remote. Your laptop talks to it over your
normal network, and so do the sandboxes, through the proxy. A local vLLM on the
Mac itself has to bind an address the VM can reach, not `127.0.0.1`.

## If it doesn't come up

`./swarm doctor` first. The failures it prints name the fix.

If `docker info` works but `openshell sandbox list` hangs, the OpenShell gateway
inside the VM didn't start; `colima restart` is the reliable fix. If the image
build fails on memory, give Colima more (`colima stop; colima start --memory
16`). If Desktop shows the bots but they never answer, it's the same client-side
issue as remote: quit the app fully and reopen it.

The rest of [troubleshooting.md](troubleshooting.md) applies as written.
