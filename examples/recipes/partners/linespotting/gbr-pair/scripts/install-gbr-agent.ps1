# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Download GitHub Release v0.6.0 gbr-agent and check a hard-coded digest.
# Do not use a website installer. Do not trust a co-downloaded SHA256SUMS
# file as the only check.

[CmdletBinding()]
param(
    [string]$Version = "v0.6.0",
    [string]$DestDir = (Join-Path $env:LOCALAPPDATA "GrokBuildRemote")
)

$ErrorActionPreference = "Stop"

$arch = $env:PROCESSOR_ARCHITECTURE
switch ($arch) {
    "AMD64" {
        $Asset = "gbr-agent-windows-amd64.exe"
        $Sha = "40355b2be6cd68f3be68f2a06dfd30307ec1a60f16f87f1d6174012b35aa4a49"
    }
    "ARM64" {
        $Asset = "gbr-agent-windows-arm64.exe"
        $Sha = "8fb9efcbc7e2ac91c11964944bf0f45e31bb23f4356d9dcb4b305d7cb9b0fe8c"
    }
    default {
        throw "unsupported Windows architecture: $arch"
    }
}

$Base = "https://github.com/LinespottingOrg/GrokBuildRemote-Agents/releases/download/$Version"
$Out = Join-Path $env:TEMP $Asset
Write-Host "Downloading $Base/$Asset"
Invoke-WebRequest -Uri "$Base/$Asset" -OutFile $Out -UseBasicParsing

$Actual = (Get-FileHash -Algorithm SHA256 -Path $Out).Hash.ToLowerInvariant()
if ($Actual -ne $Sha) {
    throw "checksum mismatch for $Asset. expected $Sha actual $Actual. abort."
}
Write-Host "$Asset SHA-256 OK"

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
$Dest = Join-Path $DestDir "gbr-agent.exe"
Copy-Item -Path $Out -Destination $Dest -Force
& $Dest version
Write-Host "installed $Dest"
