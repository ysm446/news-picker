<#
.SYNOPSIS
  Install llama.cpp (llama-server) into runtime/llama.cpp.

.DESCRIPTION
  Downloads a prebuilt llama.cpp Windows binary from GitHub Releases
  (ggml-org/llama.cpp) and installs it into <repo>/runtime/llama.cpp.
  With -Backend auto (default), cuda is selected when nvidia-smi is
  available, otherwise cpu.

.PARAMETER Backend
  auto | cpu | cuda | vulkan  (default: auto)

.PARAMETER CudaVersion
  13.3 | 12.4  (default: 13.3). Used only when Backend is cuda.
  RTX 50xx (Blackwell) GPUs require 13.3; use 12.4 only for older drivers.

.PARAMETER Tag
  Pin a specific release tag (e.g. b9870). Default: the newest release
  that has published assets (the very latest tag may still be building
  and have zero assets).

.PARAMETER Force
  Overwrite an existing installation.

.EXAMPLE
  .\scripts\install-llama-server.ps1
  .\scripts\install-llama-server.ps1 -Backend cpu
  .\scripts\install-llama-server.ps1 -Backend cuda -CudaVersion 12.4 -Force
#>
[CmdletBinding()]
param(
    [ValidateSet('auto', 'cpu', 'cuda', 'vulkan')]
    [string]$Backend = 'auto',

    [ValidateSet('13.3', '12.4')]
    [string]$CudaVersion = '13.3',

    [string]$Tag = '',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repoRoot   = Split-Path -Parent $PSScriptRoot
$installDir = Join-Path $repoRoot 'runtime\llama.cpp'
$apiBase    = 'https://api.github.com/repos/ggml-org/llama.cpp'
$headers    = @{ 'User-Agent' = 'news-picker-installer' }

# ---- resolve backend -------------------------------------------------------
if ($Backend -eq 'auto') {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $Backend = 'cuda'
    } else {
        $Backend = 'cpu'
    }
    Write-Host "[auto] backend detected: $Backend"
}

# ---- guard existing install ------------------------------------------------
$serverExe = Join-Path $installDir 'llama-server.exe'
if ((Test-Path $serverExe) -and -not $Force) {
    $infoPath = Join-Path $installDir 'install-info.json'
    if (Test-Path $infoPath) {
        Write-Host 'Already installed:'
        Get-Content $infoPath | Write-Host
    }
    throw "llama-server is already installed in $installDir. Re-run with -Force to overwrite."
}

# ---- resolve release -------------------------------------------------------
if ($Tag) {
    $release = Invoke-RestMethod -Uri "$apiBase/releases/tags/$Tag" -Headers $headers
    if ($release.assets.Count -eq 0) {
        throw "Release $Tag has no assets (its CI build may have failed or is still running)."
    }
} else {
    $releases = Invoke-RestMethod -Uri "$apiBase/releases?per_page=10" -Headers $headers
    $release = $releases | Where-Object { $_.assets.Count -gt 0 } | Select-Object -First 1
    if (-not $release) {
        throw 'No llama.cpp release with published assets was found.'
    }
}
$tagName = $release.tag_name
Write-Host "Installing llama.cpp $tagName (backend: $Backend)"

# ---- pick assets ------------------------------------------------------------
switch ($Backend) {
    'cpu'    { $wanted = @("llama-$tagName-bin-win-cpu-x64.zip") }
    'vulkan' { $wanted = @("llama-$tagName-bin-win-vulkan-x64.zip") }
    'cuda'   {
        # second zip = CUDA runtime DLLs, required unless CUDA Toolkit is installed
        $wanted = @(
            "llama-$tagName-bin-win-cuda-$CudaVersion-x64.zip",
            "cudart-llama-bin-win-cuda-$CudaVersion-x64.zip"
        )
    }
}
$assets = @()
foreach ($name in $wanted) {
    $a = $release.assets | Where-Object { $_.name -eq $name }
    if (-not $a) {
        throw "Asset not found in release ${tagName}: $name"
    }
    $assets += $a
}

# ---- download & extract ------------------------------------------------------
$work = Join-Path $env:TEMP ('llama-install-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $extractDirs = @()
    $i = 0
    foreach ($a in $assets) {
        $zip = Join-Path $work $a.name
        $mb  = [math]::Round($a.size / 1MB, 1)
        Write-Host "Downloading $($a.name) ($mb MB) ..."
        Invoke-WebRequest -Uri $a.browser_download_url -OutFile $zip -Headers $headers -UseBasicParsing
        $dst = Join-Path $work ("x{0}" -f $i)
        Expand-Archive -Path $zip -DestinationPath $dst -Force
        $extractDirs += $dst
        $i++
    }

    # locate llama-server.exe (zip layout may nest binaries under a subfolder)
    $exe = Get-ChildItem -Path $extractDirs[0] -Recurse -Filter 'llama-server.exe' |
        Select-Object -First 1
    if (-not $exe) {
        throw "llama-server.exe not found inside $($assets[0].name)."
    }
    $binDir = $exe.DirectoryName

    # merge CUDA runtime DLLs next to llama-server.exe
    if ($extractDirs.Count -gt 1) {
        Get-ChildItem -Path $extractDirs[1] -Recurse -File |
            Copy-Item -Destination $binDir -Force
    }

    # swap into place (Copy-Item: Move-Item cannot move directories across volumes)
    if (Test-Path $installDir) {
        Remove-Item -Path $installDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    Copy-Item -Path (Join-Path $binDir '*') -Destination $installDir -Recurse -Force

    $info = [ordered]@{
        tag          = $tagName
        backend      = $Backend
        installed_at = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    }
    if ($Backend -eq 'cuda') { $info['cuda_version'] = $CudaVersion }
    [IO.File]::WriteAllText(
        (Join-Path $installDir 'install-info.json'),
        ($info | ConvertTo-Json),
        [Text.UTF8Encoding]::new($false))
}
finally {
    if (Test-Path $work) {
        Remove-Item -Path $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ---- verify ------------------------------------------------------------------
& (Join-Path $installDir 'llama-server.exe') --version
if ($LASTEXITCODE -ne 0) {
    throw "llama-server.exe --version exited with code $LASTEXITCODE."
}
Write-Host ''
Write-Host "Done: llama.cpp $tagName ($Backend) -> $installDir"
Write-Host 'Next: .\scripts\start-llama-server.ps1'
