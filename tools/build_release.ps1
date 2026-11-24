# Builds dist\BorderlandsAccess-<version>.zip: the installer, the mod, and the docs.
# Usage: powershell -ExecutionPolicy Bypass -File tools\build_release.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$version = ([regex]::Match((Get-Content (Join-Path $root "bl2_access\pyproject.toml") -Raw), 'version\s*=\s*"([^"]+)"')).Groups[1].Value
$name = "BorderlandsAccess-$version"
$dist = Join-Path $root "dist"
$stage = Join-Path $dist $name
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

foreach ($f in "Install.cmd", "install.ps1", "README.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md") {
    Copy-Item (Join-Path $root $f) $stage
}
$src = Join-Path $root "bl2_access"
Get-ChildItem -Path $src -Recurse -File | Where-Object {
    $_.FullName -notmatch "\\logs\\" -and $_.FullName -notmatch "\\maps\\" -and $_.FullName -notmatch "__pycache__" -and
    $_.Name -notin @("tab_names.json", "python_path.txt")
} | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length).TrimStart("\")
    $target = Join-Path (Join-Path $stage "bl2_access") $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
    Copy-Item $_.FullName $target
}

$zip = Join-Path $dist "$name.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
# Write entries with forward slashes (Compress-Archive in Windows PowerShell 5.1 uses
# backslashes, which some unzip tools treat as part of the file name).
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem -Path $stage -Recurse -File | ForEach-Object {
        $entry = "$name/" + $_.FullName.Substring($stage.Length).TrimStart("\").Replace("\", "/")
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $_.FullName, $entry)
    }
} finally { $archive.Dispose() }
Remove-Item $stage -Recurse -Force
Write-Host "Built $zip"
