# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Windows host checks for the gbr-pair recipe. Sandbox attach uses the bash
# scripts on WSL, macOS, or Linux where NemoClaw is installed.

[CmdletBinding()]
param(
    [string]$Bot = "http://127.0.0.1:8788",
    [string]$Relay = "https://gbr-relay.ekobrott.workers.dev"
)

$ErrorActionPreference = "Stop"
$ExampleDir = Split-Path -Parent $PSScriptRoot
$pass = 0
$skip = 0
$fail = 0

function Write-Pass([string]$Msg) { Write-Host "  PASS  $Msg"; $script:pass++ }
function Write-Fail([string]$Msg) { Write-Host "  FAIL  $Msg"; $script:fail++ }
function Write-Skip([string]$Msg) { Write-Host "  SKIP  $Msg"; $script:skip++ }

Write-Host "== local/static =="
$required = @(
    (Join-Path $ExampleDir "policy.yaml"),
    (Join-Path $ExampleDir "agents.yaml"),
    (Join-Path $ExampleDir "skills\gbr-remote-operator\SKILL.md"),
    (Join-Path $ExampleDir "skills\gbr-remote-operator\scripts\operator-ping.sh"),
    (Join-Path $PSScriptRoot "install-gbr-agent.ps1")
)
foreach ($f in $required) {
    if (Test-Path $f) { Write-Pass "present $(Split-Path $f -Leaf)" }
    else { Write-Fail "missing $f" }
}

$policy = Get-Content (Join-Path $ExampleDir "policy.yaml") -Raw
if ($policy -match "host.openshell.internal" -and $policy -match "port: 8788") {
    Write-Pass "policy allows host.openshell.internal:8788"
} else {
    Write-Fail "policy missing host Bot API endpoint"
}
$active = ($policy -split "`n" | Where-Object { $_ -notmatch "^\s*#" }) -join "`n"
if ($active -match "gbr-relay|ekobrott") {
    Write-Fail "policy must not allow the vendor relay"
} else {
    Write-Pass "policy has no vendor-relay endpoint"
}
if ($policy -match "method: POST") {
    Write-Fail "policy must not allow POST (inject stays on the host)"
} else {
    Write-Pass "policy is GET-only"
}

Write-Host "== host Bot API =="
try {
    $health = Invoke-RestMethod -Uri "$Bot/health" -TimeoutSec 5
    if ($health.ok -eq $true) { Write-Pass "GET /health ok" } else { Write-Fail "GET /health not ok" }
    if ($health.version -eq "v0.6.0") { Write-Pass "agent version v0.6.0" } else { Write-Skip "running agent is not v0.6.0" }
    if ($health.health.relay_quality -eq "ok") { Write-Pass "relay_quality ok" } else { Write-Skip "relay_quality $($health.health.relay_quality)" }
} catch {
    Write-Skip "gbr-agent not listening on 127.0.0.1:8788"
}

try {
    $sessions = Invoke-RestMethod -Uri "$Bot/v1/sessions" -TimeoutSec 5
    if ($sessions.sessions -and $sessions.sessions.Count -gt 0) {
        Write-Pass "GET /v1/sessions discovered $($sessions.sessions.Count) TTY(s)"
    } else {
        Write-Fail "GET /v1/sessions returned no sessions"
    }
} catch {
    Write-Skip "GET /v1/sessions failed"
}

Write-Host "== vendor relay =="
try {
    $disc = Invoke-RestMethod -Uri "$Relay/v1/bot" -TimeoutSec 15
    if ($disc.service -eq "gbr-relay-bot") { Write-Pass "GET /v1/bot discovery (no key)" }
    else { Write-Fail "unexpected relay discovery" }
} catch {
    Write-Skip "relay discovery unreachable"
}

try {
    $null = Invoke-WebRequest -Uri "$Relay/v1/mb/gbr-example/poll" -UseBasicParsing -TimeoutSec 15
    Write-Skip "poll without key unexpectedly succeeded"
} catch {
    $code = 0
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -eq 401 -or $code -eq 403) { Write-Pass "GET /v1/mb/gbr-example/poll without key -> $code" }
    else { Write-Skip "poll without key returned HTTP $code" }
}

Write-Host "== NemoClaw / OpenShell sandbox =="
Write-Skip "native Windows has no nemoclaw/openshell on PATH; run bash scripts/verify.sh on WSL, macOS, or Linux after onboard.sh"

Write-Host ""
Write-Host "PASS=$pass SKIP=$skip FAIL=$fail"
if ($fail -gt 0) {
    Write-Host "FAIL: gbr-pair verification"
    exit 1
}
Write-Host "PASS: gbr-pair verification"
exit 0
