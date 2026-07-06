param(
    [string]$WorkspaceUrl,
    [string]$CurlLaunchUrl,
    [ValidateSet('default', 'edge', 'chrome')]
    [string]$Browser = 'default',
    [int]$WarmupSeconds = 7,
    [switch]$CreateRefreshTask,
    [int]$RefreshMinutes = 210
)

$ErrorActionPreference = 'Stop'

function Get-DesktopPath {
    $path = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -Name Desktop -ErrorAction SilentlyContinue).Desktop
    if (-not $path) {
        $path = [Environment]::GetFolderPath('Desktop')
    }
    [Environment]::ExpandEnvironmentVariables($path)
}

function Get-DirectCurlUrl {
    param([Parameter(Mandatory = $true)][string]$Text)

    $trimmed = $Text.Trim()
    if ($trimmed -match '^(?i)curl://launch/.+') {
        return $trimmed
    }

    if ($trimmed -match '(?i)(?:\?|&)next=([^&]+)') {
        return [Uri]::UnescapeDataString($Matches[1])
    }

    $index = $trimmed.IndexOf('curl://launch/', [StringComparison]::OrdinalIgnoreCase)
    if ($index -ge 0) {
        $candidate = $trimmed.Substring($index)
        $amp = $candidate.IndexOf('&')
        if ($amp -ge 0) {
            $candidate = $candidate.Substring(0, $amp)
        }
        return [Uri]::UnescapeDataString($candidate)
    }

    return $null
}

function New-PowerShellShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string]$ExtraArguments = ''
    )

    $powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $powershellPath
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" $ExtraArguments".Trim()
    $shortcut.WorkingDirectory = Split-Path -Parent $ScriptPath
    $shortcut.IconLocation = Join-Path $env:SystemRoot 'System32\shell32.dll,220'
    $shortcut.Save()
}

function Register-WorkspaceRefreshTask {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][int]$Minutes
    )

    if ($Minutes -lt 15) {
        throw 'RefreshMinutes must be at least 15.'
    }

    $powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $taskName = 'GPM Workspace Refresh'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`" -RefreshOnly"
    $action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments

    $triggers = @()
    $triggers += New-ScheduledTaskTrigger -AtLogOn

    $repeatStart = (Get-Date).AddMinutes(5)
    $repeatTrigger = New-ScheduledTaskTrigger -Once -At $repeatStart -RepetitionInterval (New-TimeSpan -Minutes $Minutes) -RepetitionDuration (New-TimeSpan -Days 3650)
    $triggers += $repeatTrigger

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel LeastPrivilege

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Description 'Refreshes the GPM workspace browser session for Curl launch.' -Force | Out-Null
    return $taskName
}

if (-not $WorkspaceUrl) {
    $WorkspaceUrl = Read-Host 'Workspace login/main URL'
}

if (-not $CurlLaunchUrl) {
    $CurlLaunchUrl = Read-Host 'Direct curl://launch URL or the temporary workspace launch URL'
}

if (-not $WorkspaceUrl.Trim()) {
    throw 'WorkspaceUrl is empty.'
}

$directCurlUrl = Get-DirectCurlUrl -Text $CurlLaunchUrl
if (-not $directCurlUrl) {
    throw 'Could not find curl://launch/... in CurlLaunchUrl.'
}

$configPath = Join-Path $PSScriptRoot 'gpm-launcher.config.json'
$config = [ordered]@{
    WorkspaceUrl  = $WorkspaceUrl.Trim()
    CurlLaunchUrl = $directCurlUrl
    Browser       = $Browser
    WarmupSeconds = $WarmupSeconds
    LastUpdated   = (Get-Date).ToString('s')
}

$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

$desktop = Get-DesktopPath
$startScript = Join-Path $PSScriptRoot 'Start-GPM.ps1'
$launchShortcut = Join-Path $desktop 'GPM Auto Launch.lnk'
$refreshShortcut = Join-Path $desktop 'GPM Workspace Refresh.lnk'

New-PowerShellShortcut -ShortcutPath $launchShortcut -ScriptPath $startScript
New-PowerShellShortcut -ShortcutPath $refreshShortcut -ScriptPath $startScript -ExtraArguments '-RefreshOnly'

Write-Host "Saved config: $configPath"
Write-Host "Created shortcut: $launchShortcut"
Write-Host "Created shortcut: $refreshShortcut"

if ($CreateRefreshTask) {
    $taskName = Register-WorkspaceRefreshTask -ScriptPath $startScript -Minutes $RefreshMinutes
    Write-Host "Created scheduled task: $taskName every $RefreshMinutes minutes and at logon"
}
