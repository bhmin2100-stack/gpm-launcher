param(
    [switch]$RefreshOnly
)

$ErrorActionPreference = 'Stop'

$configPath = Join-Path $PSScriptRoot 'gpm-launcher.config.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Config not found: $configPath. Run Setup-GPMAutoLauncher.ps1 first."
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

function Resolve-BrowserPath {
    param([Parameter(Mandatory = $true)][string]$Browser)

    $candidates = switch ($Browser.ToLowerInvariant()) {
        'edge' {
            @(
                "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
                "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
                "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
            )
        }
        'chrome' {
            @(
                "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
                "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
                "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
            )
        }
        default {
            @()
        }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Start-Workspace {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Browser
    )

    if ($Browser -eq 'default') {
        Start-Process -FilePath $Url
        return
    }

    $browserPath = Resolve-BrowserPath -Browser $Browser
    if (-not $browserPath) {
        Start-Process -FilePath $Url
        return
    }

    Start-Process -FilePath $browserPath -ArgumentList @('--new-window', $Url)
}

if (-not $config.WorkspaceUrl) {
    throw 'WorkspaceUrl is missing from config.'
}

Start-Workspace -Url $config.WorkspaceUrl -Browser ([string]$config.Browser)

if ($RefreshOnly) {
    exit 0
}

$warmupSeconds = 7
if ($config.WarmupSeconds -as [int]) {
    $warmupSeconds = [int]$config.WarmupSeconds
}

Start-Sleep -Seconds $warmupSeconds

if (-not $config.CurlLaunchUrl) {
    throw 'CurlLaunchUrl is missing from config.'
}

Start-Process -FilePath ([string]$config.CurlLaunchUrl)
