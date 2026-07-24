[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path (Join-Path $HOME ".codex") "marketplaces\kicker-interactive-manager"),
    [string]$ArchiveUrl = "https://github.com/geozocco/kicker-interactive-manager/archive/refs/heads/main.zip",
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$pluginName = "kicker-interactive-manager"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "$pluginName-$([guid]::NewGuid().ToString('N'))"
$archivePath = Join-Path $tempRoot "marketplace.zip"
$extractRoot = Join-Path $tempRoot "extracted"
$backupPath = $null

try {
    Write-Host "Lade das kicker Interactive Marketplace herunter ..."
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $archivePath
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force

    $sourceCandidates = @(
        Get-ChildItem -LiteralPath $extractRoot -Directory |
            Where-Object {
                Test-Path -LiteralPath (Join-Path $_.FullName ".agents\plugins\marketplace.json")
            }
    )
    if ($sourceCandidates.Count -ne 1) {
        throw "Das heruntergeladene Archiv enthält kein eindeutiges Codex-Marketplace."
    }

    $sourceRoot = $sourceCandidates[0].FullName
    $sourceMarketplace = Join-Path $sourceRoot ".agents\plugins\marketplace.json"
    $sourcePluginManifest = Join-Path $sourceRoot "plugins\$pluginName\.codex-plugin\plugin.json"
    if (-not (Test-Path -LiteralPath $sourcePluginManifest)) {
        throw "Das Plugin-Manifest fehlt im heruntergeladenen Marketplace."
    }

    $marketplace = Get-Content -LiteralPath $sourceMarketplace -Raw | ConvertFrom-Json
    if ($marketplace.name -ne $pluginName) {
        throw "Unerwarteter Marketplace-Name: $($marketplace.name)"
    }
    $matchingPlugins = @($marketplace.plugins | Where-Object { $_.name -eq $pluginName })
    if ($matchingPlugins.Count -ne 1) {
        throw "Das Marketplace enthält das erwartete Plugin nicht eindeutig."
    }

    $installParent = Split-Path -Parent $InstallRoot
    New-Item -ItemType Directory -Path $installParent -Force | Out-Null
    if (Test-Path -LiteralPath $InstallRoot) {
        $backupPath = "$InstallRoot.backup-$(Get-Date -Format 'yyyyMMddHHmmss')"
        if (Test-Path -LiteralPath $backupPath) {
            $backupPath = "$backupPath-$([guid]::NewGuid().ToString('N'))"
        }
        Move-Item -LiteralPath $InstallRoot -Destination $backupPath
    }

    try {
        Move-Item -LiteralPath $sourceRoot -Destination $InstallRoot
    }
    catch {
        if ($backupPath -and -not (Test-Path -LiteralPath $InstallRoot)) {
            Move-Item -LiteralPath $backupPath -Destination $InstallRoot
        }
        throw
    }

    $marketplacePath = (Resolve-Path -LiteralPath (Join-Path $InstallRoot ".agents\plugins\marketplace.json")).Path
    $encodedMarketplacePath = [System.Uri]::EscapeDataString($marketplacePath)
    $installLink = "codex://plugins/${pluginName}?marketplacePath=$encodedMarketplacePath"

    Write-Host ""
    Write-Host "Marketplace installiert: $InstallRoot"
    if ($backupPath) {
        Write-Host "Vorherige Version gesichert: $backupPath"
    }

    if ($NoLaunch) {
        Write-Host "Codex-Link: $installLink"
    }
    else {
        Write-Host "Öffne jetzt den Installationsdialog in Codex ..."
        try {
            Start-Process $installLink
            Write-Host "In Codex bitte auf 'Plugin installieren' klicken."
        }
        catch {
            Write-Warning "Codex konnte nicht automatisch geöffnet werden."
            Write-Host "Diesen Link lokal auf diesem Rechner öffnen:"
            Write-Host $installLink
        }
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
