param(
    [string]$LaunchUrl
)

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

function New-InternetShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $content = @(
        '[InternetShortcut]'
        "URL=$Url"
    )
    Set-Content -LiteralPath $Path -Value $content -Encoding ASCII
}

function New-ExplorerShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = Join-Path $env:WINDIR 'explorer.exe'
    $shortcut.Arguments = "`"$Url`""
    $shortcut.WorkingDirectory = $env:WINDIR
    $shortcut.IconLocation = Join-Path $env:WINDIR 'System32\shell32.dll,220'
    $shortcut.Save()
}

function ConvertTo-HtmlAttribute {
    param([Parameter(Mandatory = $true)][string]$Text)
    $Text.Replace('&', '&amp;').Replace('"', '&quot;').Replace('<', '&lt;').Replace('>', '&gt;')
}

if (-not $LaunchUrl) {
    $LaunchUrl = Read-Host 'Workspace에서 GPM 클릭 직후 잠깐 뜨는 전체 주소를 붙여넣으세요'
}

if (-not $LaunchUrl.Trim()) {
    throw 'URL이 비어 있습니다.'
}

$desktop = Get-DesktopPath
if (-not (Test-Path -LiteralPath $desktop)) {
    throw "Desktop path not found: $desktop"
}

$created = New-Object System.Collections.Generic.List[string]
$directCurlUrl = Get-DirectCurlUrl -Text $LaunchUrl

if ($LaunchUrl -match '^(?i)https?://') {
    $workspaceShortcut = Join-Path $desktop 'GPM - Workspace Launch.url'
    New-InternetShortcut -Path $workspaceShortcut -Url $LaunchUrl.Trim()
    $created.Add($workspaceShortcut)
}

if ($directCurlUrl) {
    $directShortcut = Join-Path $desktop 'GPM - Direct Curl.lnk'
    New-ExplorerShortcut -Path $directShortcut -Url $directCurlUrl
    $created.Add($directShortcut)

    $directUrlShortcut = Join-Path $desktop 'GPM - Direct Curl.url'
    New-InternetShortcut -Path $directUrlShortcut -Url $directCurlUrl
    $created.Add($directUrlShortcut)

    $htmlShortcut = Join-Path $desktop 'GPM - Direct Curl Fallback.html'
    $safeUrl = ConvertTo-HtmlAttribute -Text $directCurlUrl
    $html = @"
<!doctype html>
<meta charset="utf-8">
<title>GPM Direct Curl Launcher</title>
<style>
body { font-family: "Segoe UI", Arial, sans-serif; margin: 40px; color: #222; }
a { display: inline-block; padding: 12px 18px; background: #1b5eaa; color: white; text-decoration: none; border-radius: 6px; }
p { max-width: 680px; line-height: 1.5; }
</style>
<h1>GPM Direct Curl Launcher</h1>
<p>브라우저 주소창에서 curl:// 실행이 막히는 경우 아래 버튼을 클릭하세요.</p>
<a href="$safeUrl">GPM 실행</a>
"@
    Set-Content -LiteralPath $htmlShortcut -Value $html -Encoding UTF8
    $created.Add($htmlShortcut)
}

if ($created.Count -eq 0) {
    throw '바로가기를 만들 수 있는 GPM URL 형식을 찾지 못했습니다. http(s) 주소 또는 curl://launch/... 주소를 넣어 주세요.'
}

Write-Host 'Created desktop launcher(s):'
$created | ForEach-Object { Write-Host " - $_" }

if (-not $directCurlUrl) {
    Write-Host ''
    Write-Host '참고: 붙여넣은 주소에서 curl://launch/... 값을 찾지 못해서 Workspace용 링크만 만들었습니다.'
}
