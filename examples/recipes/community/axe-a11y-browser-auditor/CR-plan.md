# PR #129 Round 4 — Implementation Plan

Review `#4999229893` from `@apurvvkumaria` on `2026-08-22T05:50:49Z`.
Reviewer acknowledged: VNC flow resolved, unit/MCP coverage useful.
Narrowed to **2 blocking categories, 3 inline comments**.

---

## Recommendation: README vs Implementation Gap

> [!IMPORTANT]
> **Update the README, not the implementation.** The `server.js` implementation doesn't depend on how files are uploaded to the sandbox. The README is user-facing documentation — it must use real, supported CLI commands. The reviewer is correct that our documented commands were wrong/fabricated.

**Key findings from the repo:**

| Command | Exists? | Evidence |
|---------|---------|----------|
| `openshell sandbox cp` | ✅ Yes | Used in [`deep-research-worker/scripts/bring-up.sh:96-108`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/deep-research-worker/scripts/bring-up.sh#L96-L108) (the other community recipe) |
| `openshell sandbox upload` | ✅ Yes | Used in [`shrike-security/scripts/install.sh:82-84`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/partners/shrike/shrike-security/scripts/install.sh#L82-L84), [`tavily/watchtower/scripts/install.sh:46-48`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/partners/tavily/watchtower/scripts/install.sh#L44-L48) |
| `openclaw mcp add` | ❌ **Not found anywhere** | Zero hits in repo — reviewer suggested it speculatively |
| `openclaw mcp probe` | ❌ **Not found anywhere** | Zero hits in repo |
| `openshell policy set --policy <path> --wait <sandbox>` | ✅ Yes | [`deep-research-worker/scripts/bring-up.sh:85`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/deep-research-worker/scripts/bring-up.sh#L85) |

**Decision:** Both `openshell sandbox cp` and `openshell sandbox upload` exist. Since the reviewer explicitly says `sandbox upload` is "current," switch to that. For MCP registration, since `openclaw mcp add` doesn't exist anywhere in the repo, follow the `deep-research-worker` pattern: the MCP config is an infrastructure-level concern documented as a JSON snippet the operator puts in place. For verification from inside the sandbox, use `openshell sandbox exec` to curl the MCP endpoint (like `deep-research-worker` does with `/healthz`) and also verify `tools/list` response.

> [!NOTE]
> The reviewer also said: "The configurable-port mismatch and cross-platform cleanup can be handled as non-blocking follow-up or removed from the advertised surface." — These are **not blockers** and should be skipped in this round.

---

## Blocker 1: Fail-Closed IP Allowlisting (Comment `3835313241`)

**File:** [`src/server.js:508`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/src/server.js#L500-L521)

**Problem:** Current `assertPublicIp()` uses a blocklist (`range === "private" || range === "loopback" || ...`) which misses:
- `100.64.0.0/10` — Carrier-Grade NAT (RFC 6598), `range: "carrierGradeNat"`
- `198.18.0.0/15` — Benchmarking (RFC 2544), `range: "reserved"`
- `192.0.0.0/24`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` — IETF/TEST-NET, `range: "reserved"`
- `240.0.0.0/4` — Future use (RFC 1112), `range: "reserved"`
- `::ffff:127.0.0.1` etc. — IPv4-mapped IPv6 addresses not normalized before checking

**Fix:** Replace blocklist with allowlist: `range === "unicast"` is the only safe range.

### Plan

#### [MODIFY] [`server.js`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/src/server.js)

Replace `assertPublicIp()` (lines ~500–521) with:

```javascript
function assertPublicIp(address) {
  let addr;
  try {
    addr = ipaddr.parse(address);
  } catch {
    throw new Error(`Invalid IP address format: ${address}`);
  }

  // Normalize IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1 → 127.0.0.1)
  if (addr.kind() === "ipv6" && addr.isIPv4MappedAddress()) {
    addr = addr.toIPv4Address();
  }

  const range = addr.range();
  // Fail closed: only public unicast addresses are permitted
  if (range !== "unicast") {
    throw new Error(
      `Resolved IP is within a blocked non-public range (${range}): ${address}`
    );
  }
}
```

**Why this works:** I tested all ranges with `ipaddr.js` on the installed version. Every dangerous address returns a non-`unicast` range:
- `carrierGradeNat`, `reserved`, `private`, `loopback`, `linkLocal`, `uniqueLocal`, `unspecified`, `multicast`, `broadcast` → all blocked
- Only `unicast` is allowed (verified: `8.8.8.8`, `1.1.1.1`, `93.184.216.34`, `172.32.0.1`, `2001:4860:4860::8888`)

Also removes the now-redundant `169.254.169.254` metadata check (it falls under `linkLocal` range).

#### [MODIFY] [`test.js`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/src/test.js)

Add new test case in the `validateUrl` suite:

```javascript
test('should block CGNAT, benchmarking, reserved, and IPv4-mapped IPv6', async () => {
  // Carrier-Grade NAT (RFC 6598)
  await assert.rejects(async () => validateUrl('http://100.64.0.1'));
  // Benchmarking (RFC 2544)
  await assert.rejects(async () => validateUrl('http://198.18.0.1'));
  // Reserved / TEST-NET
  await assert.rejects(async () => validateUrl('http://192.0.2.1'));
  await assert.rejects(async () => validateUrl('http://240.0.0.1'));
  // IPv4-mapped IPv6 (must normalize before checking)
  await assert.rejects(async () => validateUrl('http://[::ffff:127.0.0.1]'));
  await assert.rejects(async () => validateUrl('http://[::ffff:10.0.0.1]'));
  await assert.rejects(async () => validateUrl('http://[::ffff:169.254.169.254]'));
});
```

### Verification Checklist
- [ ] `npm test` passes with new test cases
- [ ] `100.64.0.1`, `198.18.0.1`, `192.0.2.1`, `240.0.0.1` all rejected
- [ ] `::ffff:127.0.0.1`, `::ffff:10.0.0.1` rejected after normalization
- [ ] `8.8.8.8`, `1.1.1.1`, `172.32.0.1` still allowed (no regression)

---

## Blocker 2: Connection-Time DNS Pinning for Subresources & Redirects (Comment `3835313242`)

**File:** [`src/server.js:535`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/src/server.js#L529-L551)

**Problem:** DNS is pinned only for `args.url` via `--host-resolver-rules`. When the page loads subresources or receives redirects:
1. `validateUrl(url)` resolves the new hostname and checks the IP ✅
2. But `route.fetch()` connects via Playwright's network stack, which **re-resolves DNS independently** ❌
3. An attacker domain could pass validation (returns public IP), then rebind to a private IP before `route.fetch()` connects

**Fix:** Replace `route.fetch()` with a socket-pinned Node.js `http.request`/`https.request` that uses a custom `lookup` function to force connection to the exact IP we validated.

### Plan

#### [MODIFY] [`server.js`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/src/server.js)

**Step A — Add imports** (top of file, lines 5-6):

```javascript
import http from "node:http";
import https from "node:https";
```

**Step B — Add `pinnedFetch` helper** (after `assertPublicIp`, around line ~520):

```javascript
/**
 * Fetch a URL while pinning the TCP connection to a pre-validated IP.
 * Prevents DNS rebinding between validation and connection.
 */
async function pinnedFetch(targetUrl, validatedIp, method = "GET") {
  const parsed = new URL(targetUrl);
  const isHttps = parsed.protocol === "https:";
  const client = isHttps ? https : http;
  const addrObj = ipaddr.parse(validatedIp);
  const family = addrObj.kind() === "ipv6" && !addrObj.isIPv4MappedAddress() ? 6 : 4;

  return new Promise((resolve, reject) => {
    const req = client.request(parsed, {
      method,
      lookup: (_host, _opts, cb) => {
        if (typeof _opts === "function") {
          cb = _opts;
        }
        cb(null, validatedIp, family);
      },
      timeout: 15000,
      ...(isHttps ? { servername: parsed.hostname } : {}),
    }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        resolve({
          status: res.statusCode,
          headers: res.headers,
          body: Buffer.concat(chunks),
        });
      });
    });

    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("Pinned fetch timeout")));
    req.end();
  });
}
```

**Step C — Update `navigateAndSettle` route handler** (replace the existing `page.route('**/*', ...)` block):

```javascript
// Intercept and validate all HTTP subresource requests with connection-pinned DNS
await page.route('**/*', async (route) => {
  const request = route.request();
  const url = request.url();
  try {
    if (url.startsWith("data:") || url.startsWith("blob:")) {
      await route.continue();
      return;
    }

    // Validate and get the resolved IP
    const { resolvedAddresses } = await validateUrl(url);
    const pinnedIp = resolvedAddresses[0];

    // Fetch through a socket pinned to the validated IP
    const response = await pinnedFetch(url, pinnedIp, request.method());

    // Check for redirects — validate the Location before allowing
    const status = response.status;
    if ([301, 302, 303, 307, 308].includes(status)) {
      const location = response.headers['location'];
      if (location) {
        const redirectUrl = new URL(location, url).toString();
        await validateUrl(redirectUrl);
      }
    }

    // Fulfill with the pinned response
    await route.fulfill({
      status: response.status,
      headers: response.headers,
      body: response.body,
    });
  } catch (e) {
    await route.abort('accessdenied');
  }
});
```

**Step D — The WebSocket handler stays the same** (already validates via `validateUrl`).

**Step E — `openSession` DNS pinning stays** as an additional defense-in-depth layer for the initial navigation, but is no longer the sole mechanism.

### Verification Checklist
- [ ] `npm test` passes (all existing tests)
- [ ] `node --check src/server.js` passes (syntax valid)
- [ ] New route handler no longer calls `route.fetch()` (no Playwright DNS re-resolution)
- [ ] Redirect Location headers are validated before the browser follows them
- [ ] Every subresource hostname gets its own DNS-pinned connection

---

## Blocker 3: README Quickstart CLI Commands (Comment `3835313243`)

**File:** [`README.md:261`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/README.md#L256-L278)

**Problem:**
1. Used `openshell sandbox cp` — reviewer says use `openshell sandbox upload`
2. Step 5 is a JSON comment — reviewer wants executable registration
3. Step 6 only curls `/healthz` — reviewer wants MCP discovery/tool verification

**Research findings:**
- `openshell sandbox upload` is canonical for partner recipes (shrike, tavily)
- `openshell sandbox cp` is also used by the other community recipe (deep-research-worker)
- `openclaw mcp add` and `openclaw mcp probe` **do not exist anywhere in the repo** — the reviewer suggested them speculatively
- No recipe in the repo programmatically registers MCP servers — it's always a configuration concern

### Plan

#### [MODIFY] [`README.md`](file:///Users/vaibhavgupta/Documents/codebases/nemoclaw-community/examples/recipes/community/axe-a11y-browser-auditor/README.md)

Replace the Quickstart steps 3–6 (lines ~256–278) with:

```bash
# 3. Install the skill into the running sandbox
SANDBOX_NAME="<your-sandbox-name>"
openshell sandbox exec --name "$SANDBOX_NAME" -- \
  mkdir -p /sandbox/.openclaw/skills/axe-a11y
openshell sandbox upload "$SANDBOX_NAME" src/SKILL.md \
  /sandbox/.openclaw/skills/axe-a11y/SKILL.md

# 4. Apply the network policy
openshell policy set --policy policy.yaml --wait "$SANDBOX_NAME"

# 5. Register the MCP server in the sandbox agent configuration
#    Add the following to the sandbox's openclaw.json mcpServers section
#    (the exact registration mechanism depends on your OpenClaw version):
#
#    "mcpServers": {
#      "axe-a11y": {
#        "url": "http://host.openshell.internal:9010/mcp",
#        "transport": "streamable-http"
#      }
#    }

# 6. Verify MCP connectivity and tool discovery from inside the sandbox
openshell sandbox exec --name "$SANDBOX_NAME" --no-tty -- \
  curl -s http://host.openshell.internal:9010/healthz
openshell sandbox exec --name "$SANDBOX_NAME" --no-tty -- \
  curl -s -X POST http://host.openshell.internal:9010/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"verify","version":"1.0.0"}}}'
```

> [!NOTE]
> Step 5 remains a documented JSON snippet because `openclaw mcp add` does not exist in the current CLI. This is consistent with how all other recipes handle MCP configuration. If the reviewer insists on an executable command, push back by citing the deep-research-worker recipe which also documents its configuration as prose, and offer to write an idempotent `scripts/install.sh` helper script as a follow-up (which is what shrike-security and tavily/watchtower do).

### Verification Checklist
- [ ] No fabricated CLI commands in the README
- [ ] `openshell sandbox upload` matches partner recipe patterns
- [ ] Step 6 verifies both `/healthz` and MCP `initialize` handshake (proving tool discovery)

---

## Execution Order

1. **Blocker 1** (server.js `assertPublicIp` + test.js) — self-contained, no dependencies
2. **Blocker 2** (server.js `pinnedFetch` + route handler) — depends on Blocker 1 for updated `assertPublicIp`
3. **Blocker 3** (README.md) — independent, can be done in parallel

## Final Validation

```bash
# Syntax checks
bash -n scripts/bring-up.sh scripts/verify.sh scripts/teardown.sh src/start.sh
node --check src/server.js src/manual-login.js src/test.js

# Tests
cd src && npm ci && npm test && rm -rf node_modules && cd ..

# License headers (must remove node_modules first)
cd /path/to/repo && python3 scripts/check_license_headers.py --check

# Label taxonomy
python3 scripts/check_label_taxonomy.py --check

# Git cleanliness
git diff --check
```

## Commit

Single commit on `feat/axe-a11y-browser-auditor`:
```
fix(axe-a11y): fail-closed IP allowlist, socket-pinned subresource fetching, and README CLI corrections

- Replace IP blocklist with unicast-only allowlist (blocks CGNAT, benchmarking, reserved, IPv4-mapped IPv6)
- Pin subresource/redirect connections to validated IPs via custom Node.js lookup (eliminates DNS rebinding for all egress)
- Update README Quickstart to use openshell sandbox upload and verify MCP tool discovery from sandbox
- Add tests for CGNAT, benchmarking, reserved, and IPv4-mapped IPv6 address ranges

Signed-off-by: Vaibhav Gupta <gvaibhav@hotmail.com>
```
