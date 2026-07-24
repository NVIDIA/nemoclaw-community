Here's the complete list of changes required by the NemoClaw v2026.5.18 upgrade, version v0.0.50, relevant for any deployment method:

---

### **1. `plugins.allow` must be removed**

**What changed:** New version changed plugin loading. A stale `plugins.allow` array in `openclaw.json` blocks plugins from registering.

**Fix:** Delete the `plugins.allow` key entirely from the config.

```jsx
plugins.pop('allow', None)  // in patch script
// or delete config.plugins.allow from openclaw.json
```

### **2. `tools.toolSearch` must be `false`**

**What changed:** New version introduced a JavaScript "tool search" proxy surface. When enabled, it intercepts tool calls and breaks the `exec` tool flow.

**Fix:** Set `tools.toolSearch = false` in `openclaw.json`.

### **3. Node.js 22 `EnvHttpProxyAgent` proxy bypass**

**What changed:** The sandbox now uses Node.js 22, which has a built-in `EnvHttpProxyAgent`. If `HTTP_PROXY` / `HTTPS_PROXY` env vars are set (and they are — OpenShell sets them to `10.200.0.1:3128`), ALL `http.request()` calls get routed through the proxy automatically.

**Fix:** Any custom Node.js script (like `retail-api.js`) that makes HTTP requests must create a direct agent:

```jsx
const directAgent = new http.Agent();
// then in every http.request call:
http.request(url, { agent: directAgent, ... })
```

### **4. Exec tool sandbox network restriction**

**What changed:** Exec tool child processes now run in a restricted network namespace. They can **only** reach `10.200.0.1` (the veth bridge). They **cannot** reach `host.openshell.internal`, `172.18.0.x`, `localhost`, or any other address.

**Fix:** Any URL used by exec'd scripts must point to `10.200.0.1:PORT`. You need a TCP relay listening on `10.200.0.1` in the sandbox's default namespace that forwards to the actual service. The `10.200.0.1` / `10.200.0.2` pair is deterministic — OpenShell always creates it.

### **5. TCP relay needed on `10.200.0.1`**

**What changed:** Consequence of #4. The retail API (or any service) isn't directly reachable from exec'd processes.

**Fix:** Run a relay inside the sandbox (default namespace) on `10.200.0.1:8001` forwarding to wherever the retail API actually lives. In K8s we used a Python socket relay; in docker-compose you could use socat:

- docker exec SANDBOX socat TCP-LISTEN:8001,bind=10.200.0.1,fork,reuseaddr TCP:HOST:PORT &

### **6. Telegram proxy removal**

**What changed:** New version doesn't need/want proxy settings on Telegram accounts.

**Fix:** Remove `proxy` key from Telegram account config in `openclaw.json`.

### **7. Telegram polling — kill -9, not SIGUSR1**

**What changed:** SIGUSR1 (in-process restart) doesn't clean up Telegram poller threads. Stale pollers cause "refusing duplicate poller" errors.

**Fix:** When restarting the gateway after config changes, use `kill -9 PID` (PID 1/openshell-sandb will auto-restart it), not `kill -USR1`.

### **8. `tools.deny` for `web_fetch` and `browser`**

**What changed:** These tools can cause the agent to go off-script. Already may have been set before, but worth confirming.

**Fix:** `tools.deny = ['web_fetch', 'browser']` in `openclaw.json`.

### **9. Gateway binary path fix (DinD / Docker-in-Docker)**

**What changed:** The new version's gateway binary (`openshell-gateway`) requires **glibc 2.39** (Ubuntu 24.04), so it runs inside a Docker container. `nemoclaw onboard` tries to bind-mount the binary from `/usr/local/bin/openshell-gateway` into that container. But in a DinD setup, Docker bind mounts resolve from the **DinD daemon's filesystem**, not the workspace's. `/usr/local/bin/openshell-gateway` doesn't exist on DinD's filesystem → **permission denied / file not found**.

**Fix:** Copy the binaries to a **shared volume** (run, which is an `emptyDir` volume visible to both workspace and DinD), then pre-start the gateway container yourself with corrected paths:

```jsx
# Copy binaries to shared volume
cp /usr/local/bin/openshell-gateway /var/run/openshell-gateway
cp /usr/local/bin/openshell-sandbox /var/run/openshell-sandbox
chmod +x /var/run/openshell-gateway /var/run/openshell-sandbox

# Tell nemoclaw CLI to use the new paths
export NEMOCLAW_OPENSHELL_GATEWAY_BIN=/var/run/openshell-gateway
export NEMOCLAW_OPENSHELL_SANDBOX_BIN=/var/run/openshell-sandbox

# Pre-start the gateway compat container with shared-volume mounts
docker run -d --rm --name nemoclaw-openshell-gateway --network host \
  --volume /var/run/openshell-gateway:/opt/nemoclaw/openshell-gateway:ro \
  --volume /var/run/openshell-sandbox:/var/run/openshell-sandbox:ro \
  --volume /var/run/nemoclaw-state:/var/run/nemoclaw-state:rw \
  --volume /var/run/docker.sock:/var/run/docker.sock:rw \
  ubuntu:24.04 /opt/nemoclaw/openshell-gateway

# Then run: nemoclaw onboard --fresh
# It detects the already-running gateway and skips the broken mount
```

### **10. No `socat` in sandbox — use Python TCP relay instead**

**What changed:** The new sandbox image doesn't include `socat`. In the old version you could `docker exec $SANDBOX socat ...` to create relays inside the sandbox.

**Fix:** Use Python's `socket` + `threading` modules instead (Python3 is available in the sandbox). That's why the relay in the startup script uses an inline Python script rather than socat:

```jsx
# This FAILS in the new sandbox:
docker exec $SANDBOX socat TCP-LISTEN:8001,bind=10.200.0.1,fork TCP:172.18.0.1:8001

# This WORKS:
docker exec $SANDBOX python3 -c "
import socket, threading
def relay(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data: break
            dst.sendall(data)
    except: pass
    finally: src.close(); dst.close()
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('10.200.0.1', 8001))
srv.listen(5)
while True:
    c, _ = srv.accept()
    u = socket.socket()
    u.connect(('172.18.0.1', 8001))
    threading.Thread(target=relay, args=(c, u), daemon=True).start()
    threading.Thread(target=relay, args=(u, c), daemon=True).start()
" &
```

**Docker-compose note:** Same limitation — use Python relay inside the sandbox. `socat` is available on the **workspace** container (we install it there), but not inside the sandbox.

---

### **11. `openshell policy set` fails on live sandbox with filesystem path changes**

**What changed:** The new version validates policy changes against the running sandbox state. If your policy YAML removes a `read_write` filesystem path (like `/home/linuxbrew`) that the running sandbox has, it rejects the change with `InvalidArgument`.

**Fix:** Two options:

1. **Apply the policy before the sandbox starts** (during onboard/rebuild) — but this requires integration with the build pipeline
2. **Ensure your policy YAML includes all default filesystem paths** — don't remove paths that the sandbox was created with. The error specifically mentions `/home/linuxbrew`, so your `policy.yaml` must keep that path in the `read_write` list

In our current startup script, this error is non-fatal — the `policy set` command outputs the error but the bot still works because the default policy is permissive enough. But if you need custom policy restrictions, you need to match the sandbox's existing filesystem paths.


### **12. Force-install nemoclaw plugin (exec tool)**

**What changed:** The new version doesn't auto-register the nemoclaw plugin (which provides the `exec` tool). Without it, the agent has no way to run commands.

**Fix:** Force-install from inside the sandbox:

```jsx
docker exec $SANDBOX su -s /bin/sh sandbox -c \
  'openclaw plugins install /opt/nemoclaw --dangerously-force-unsafe-install --force'
```

The `--dangerously-force-unsafe-install` flag is needed because the plugin path (`/opt/nemoclaw`) isn't in the default trusted plugin directory. The `--force` overwrites any partial/stale registration.

---

### **13. File ownership fix (`chown sandbox:sandbox`)**

**What changed:** When you copy files into the sandbox via `docker exec` (as root), they're owned by `root:root`. But OpenClaw runs as user `sandbox`. Skills, `.env`, `SKILL.md` — all unreadable by the agent.

**Fix:** After copying any files into the sandbox:

```jsx
docker exec $SANDBOX sh -c \
  "chown -R sandbox:sandbox /sandbox/.openclaw/skills/ /sandbox/.openclaw/workspace/ 2>/dev/null; \
   chmod -R a+r /sandbox/.openclaw/skills/ 2>/dev/null"
```


---

### **Docker-compose specific notes:**

- Items **1, 2, 3, 6, 7, 8, 9, 10, 11** apply identically
- Items **4, 5** (network relay) apply but the forwarding target will differ — in docker-compose the retail API container is on the compose network, so the relay target is the container's IP or service name resolvable from the sandbox's default namespace
- The `10.200.0.1` address is the same regardless of K8s or docker-compose — it's OpenShell internal

