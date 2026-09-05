# certs/

Optional drop point for additional CA certificates used by the Hermes image
build and trusted inside the final sandbox image. Files placed here are
installed in the derived sandbox image and retained so `curl`, Python, native
NeMo Relay, and other TLS clients inside the sandbox trust the corresponding
roots.

## When you need this

If the network running this example performs TLS interception (for example, a
proxy that re-signs HTTPS traffic with its own CA), agent calls to the public
internet will fail with errors like `SSL certificate problem: self-signed
certificate in certificate chain`. Place the interception CA(s) here to
register them as trusted roots.

If TLS traffic is not being intercepted, leave this directory empty. The
Dockerfile's `update-ca-certificates` step becomes a no-op and the build
succeeds as-is.

## Usage

1. Copy your CA certificate(s) into this directory. PEM-encoded, with a
   `.crt` extension — `update-ca-certificates` only picks up `*.crt`.

   ```bash
   cp /path/to/corp-proxy-ca.pem ./corp-proxy-ca.crt
   ```

2. Rebuild the Hermes sandbox by re-running bring-up:

   ```bash
   bash scripts/bring-up.sh
   ```

The Dockerfile copies everything in this directory into
`/usr/local/share/ca-certificates/` and runs `update-ca-certificates` to
register the new trust roots.

### Locally installed enterprise CAs

On Linux hosts, `scripts/03-sandbox.sh` automatically stages readable `*.crt`
files from `/usr/local/share/ca-certificates/`. This directory conventionally
contains operator-installed roots rather than distribution-managed roots.
Override the source with `NEMOCLAW_ENTERPRISE_CA_SOURCE_DIR` when additional
roots are kept in another dedicated directory.

The copied files remain ignored by Git through the repository-wide `*.crt`
rule. Other environments can continue to place their public CA certificates in
this directory before bring-up.
