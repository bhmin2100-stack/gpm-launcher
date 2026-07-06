$ErrorActionPreference = 'Stop'

$RepoOwner = 'bhmin2100-stack'
$RepoName = 'gpm-launcher'
$RepoFullName = "$RepoOwner/$RepoName"
$RepoUrl = "https://github.com/$RepoFullName.git"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Gh = Get-ChildItem -Path (Join-Path $Root 'tools\gh') -Recurse -Filter gh.exe -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $Gh) {
    throw 'GitHub CLI not found under tools\gh. Re-run the Codex setup or install gh.'
}

Set-Location $Root

Write-Host 'GPM Launcher GitHub upload'
Write-Host "Repo: $RepoFullName"
Write-Host ''

git status --short --branch
Write-Host ''

try {
    & $Gh auth status
} catch {
    Write-Host ''
    Write-Host 'GitHub CLI is not logged in. Starting browser/device login...'
    & $Gh auth login --hostname github.com --web --git-protocol https --scopes repo
}

Write-Host ''
Write-Host 'Checking repository...'
$repoExists = $true
try {
    & $Gh repo view $RepoFullName | Out-Host
} catch {
    $repoExists = $false
}

if (-not $repoExists) {
    Write-Host ''
    Write-Host 'Creating private repository and pushing current branch...'
    & $Gh repo create $RepoFullName --private --source $Root --remote origin --push
} else {
    Write-Host ''
    Write-Host 'Repository exists. Pushing current branch...'
    $remote = git remote get-url origin 2>$null
    if (-not $remote) {
        git remote add origin $RepoUrl
    } else {
        git remote set-url origin $RepoUrl
    }
    git push -u origin main
}

Write-Host ''
Write-Host 'Done. Repository URL:'
Write-Host "https://github.com/$RepoFullName"
Write-Host ''
Read-Host 'Press Enter to close'
