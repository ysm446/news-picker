<#
.SYNOPSIS
  Start Ornith-1.0 llama-server instances (9B: port 8081, 35B: port 8082).

.DESCRIPTION
  Launches llama-server from runtime/llama.cpp with the GGUF models under
  models/. Ports and roles follow docs/news-picker-spec.md section 3:
    - 9B  -> 127.0.0.1:8081 (background summarization)
    - 35B -> 127.0.0.1:8082 (deep-dive agentic chat)

.PARAMETER Model
  9b | 35b | both  (default: both)

.PARAMETER Ctx9b
  Context length for the 9B server (default: 32768).

.PARAMETER Ctx35b
  Context length for the 35B server (default: 65536; VRAM permitting,
  up to 131072).

.PARAMETER GpuLayers
  -ngl value passed to llama-server (default: 999 = fully offload).
  Ignored by CPU builds.

.EXAMPLE
  .\scripts\start-llama-server.ps1
  .\scripts\start-llama-server.ps1 -Model 9b
  .\scripts\start-llama-server.ps1 -Model 35b -Ctx35b 131072
#>
[CmdletBinding()]
param(
    [ValidateSet('9b', '35b', 'both')]
    [string]$Model = 'both',

    [int]$Ctx9b = 32768,

    [int]$Ctx35b = 65536,

    [int]$GpuLayers = 999
)

$ErrorActionPreference = 'Stop'

$repoRoot  = Split-Path -Parent $PSScriptRoot
$serverExe = Join-Path $repoRoot 'runtime\llama.cpp\llama-server.exe'
if (-not (Test-Path $serverExe)) {
    throw 'llama-server not found. Run .\scripts\install-llama-server.ps1 first.'
}

$servers = @{
    '9b'  = @{
        Path  = Join-Path $repoRoot 'models\Ornith-1.0-9B-GGUF\ornith-1.0-9b-Q4_K_M.gguf'
        Port  = 8081
        Ctx   = $Ctx9b
        Alias = 'ornith-9b'
    }
    '35b' = @{
        Path  = Join-Path $repoRoot 'models\Ornith-1.0-35B-GGUF\ornith-1.0-35b-Q4_K_M.gguf'
        Port  = 8082
        Ctx   = $Ctx35b
        Alias = 'ornith-35b'
    }
}

if ($Model -eq 'both') { $targets = @('9b', '35b') } else { $targets = @($Model) }

foreach ($key in $targets) {
    $s = $servers[$key]
    if (-not (Test-Path $s.Path)) {
        throw "Model file not found: $($s.Path)"
    }
    # already running on this port? skip (avoids double start from start.bat)
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:$($s.Port)/health" -UseBasicParsing -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            Write-Host "$($s.Alias) already running on port $($s.Port), skipping."
            continue
        }
    } catch {
        # not running -> start below
    }
    # --jinja enables the chat template incl. tool-call parsing and
    # reasoning_content separation for Qwen3-based Ornith models.
    $argList = @(
        '-m', ('"{0}"' -f $s.Path),
        '--host', '127.0.0.1',
        '--port', $s.Port,
        '-c', $s.Ctx,
        '-ngl', $GpuLayers,
        '--jinja',
        '--alias', $s.Alias
    )
    Write-Host "Starting $($s.Alias) on 127.0.0.1:$($s.Port) (ctx: $($s.Ctx)) ..."
    Start-Process -FilePath $serverExe -ArgumentList $argList
}

Write-Host ''
Write-Host 'Health check:'
foreach ($key in $targets) {
    Write-Host "  http://127.0.0.1:$($servers[$key].Port)/health"
}
