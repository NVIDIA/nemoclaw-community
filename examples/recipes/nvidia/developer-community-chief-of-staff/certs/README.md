# certs/

Optional drop point for additional CA certificates to trust inside the Hermes
sandbox image. Files placed here are baked in at build time so `curl` and
other TLS clients inside the sandbox trust the corresponding roots.

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
