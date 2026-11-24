# Borderlands Access installer.
#
# Double-click Install.cmd, or run:  powershell -ExecutionPolicy Bypass -File install.ps1
#
# What it does, asking before anything that changes your PC outside the game folder:
#   1. Finds Borderlands 2 in your Steam libraries (or use -GameDir).
#   2. Installs the Borderlands 2 mod manager (willow2-mod-manager v3.8) into the game folder,
#      unless it's already installed. The download is checked against a known SHA-256.
#   3. Checks for the Microsoft Visual C++ x86 runtime the mod manager needs; offers to install it.
#   4. Checks for a 64-bit Python (used to talk to your screen reader through Prism); offers to
#      install it with winget.
#   5. Copies the Borderlands Access mod into the game's sdk_mods folder. Your mod settings are
#      kept: they live in sdk_mods\settings, which this never touches.
#   6. Sets Steam to skip the inaccessible 2K launcher (closes and reopens Steam).
#
# Everything is written as plain text so your screen reader reads it. Yes/no questions take
# Y or N then Enter.
#
# Options:
#   -GameDir <path>     Borderlands 2 folder, if it isn't found automatically
#   -Yes                answer yes to every question (unattended install)
#   -CheckOnly          only report what would be done; change nothing
#   -SkipLauncherFix    don't change Steam's launch options
#   -SkipPrerequisites  don't check for the Visual C++ runtime or Python
#   -SdkZip <path>      use a local copy of willow2-sdk.zip instead of downloading it
#   -ReinstallSdk       reinstall the mod manager even if it's already there

param(
    [string]$GameDir = "",
    [switch]$Yes,
    [switch]$CheckOnly,
    [switch]$SkipLauncherFix,
    [switch]$SkipPrerequisites,
    [string]$SdkZip = "",
    [switch]$ReinstallSdk
)

$ErrorActionPreference = "Stop"
$ModVersion = "0.1.0"
$SdkVersion = "v3.8"
$SdkUrl = "https://github.com/bl-sdk/willow2-mod-manager/releases/download/v3.8/willow2-sdk.zip"
$SdkSha256 = "e1862ddb282cf845369c9ca1ca70ac180d6104cce25d8a133557fc74e157b4c7"
$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x86.exe"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModSource = Join-Path $Here "bl2_access"

function Say([string]$text) { Write-Host $text }
function Ask([string]$question) {
    if ($Yes) { Say "$question Yes."; return $true }
    if ($CheckOnly) { Say "$question (check only: not asking)"; return $false }
    while ($true) {
        $a = Read-Host "$question Type Y for yes or N for no, then press Enter"
        if ($a -match '^\s*y') { return $true }
        if ($a -match '^\s*n') { return $false }
    }
}
function Fail([string]$text) {
    Say "Installation stopped: $text"
    if (-not $Yes) { Read-Host "Press Enter to close" | Out-Null }
    exit 1
}

# ------------------------------------------------------------------ find the game
function Find-SteamRoot {
    foreach ($k in "HKCU:\Software\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam", "HKLM:\SOFTWARE\Valve\Steam") {
        try {
            $p = (Get-ItemProperty $k -ErrorAction Stop)
            foreach ($name in "SteamPath", "InstallPath") {
                $v = $p.$name
                if ($v -and (Test-Path $v)) { return ($v -replace "/", "\") }
            }
        } catch {}
    }
    return $null
}

function Find-Game {
    $libraries = @()
    $steam = Find-SteamRoot
    if ($steam) {
        $libraries += $steam
        $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) {
                $libraries += ($m.Groups[1].Value -replace "\\\\", "\")
            }
        }
    }
    $libraries += "C:\Program Files (x86)\Steam", "C:\Program Files\Steam"
    foreach ($lib in ($libraries | Select-Object -Unique)) {
        $dir = Join-Path $lib "steamapps\common\Borderlands 2"
        if (Test-Path (Join-Path $dir "Binaries\Win32\Borderlands2.exe")) { return $dir }
    }
    return $null
}

Say "Borderlands Access $ModVersion installer."
if ($CheckOnly) { Say "Check only: nothing will be changed." }
if (-not (Test-Path (Join-Path $ModSource "__init__.py"))) {
    Fail "the bl2_access folder wasn't found next to this script. Extract the whole zip first, then run Install.cmd from the extracted folder."
}

if (-not $GameDir) { $GameDir = Find-Game }
while (-not $GameDir -or -not (Test-Path (Join-Path $GameDir "Binaries\Win32\Borderlands2.exe"))) {
    if ($Yes -or $CheckOnly) { Fail "Borderlands 2 wasn't found. Run again with -GameDir and the game's folder." }
    Say "Borderlands 2 wasn't found automatically."
    $GameDir = (Read-Host "Type the full path of your Borderlands 2 folder (the one containing Binaries), then press Enter").Trim('"', ' ')
}
Say "Found Borderlands 2 in $GameDir"

$exe = (Resolve-Path (Join-Path $GameDir "Binaries\Win32\Borderlands2.exe")).Path
$running = Get-Process Borderlands2 -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -and ((Resolve-Path $_.Path).Path -eq $exe) } catch { $true }  # can't tell: assume it's this one
}
if ($running) {
    if ($CheckOnly) { Say "Borderlands 2 is running. It must be closed before installing." }
    else { Fail "Borderlands 2 is running. Close the game, then run the installer again." }
}

$Win32 = Join-Path $GameDir "Binaries\Win32"
$SdkMods = Join-Path $GameDir "sdk_mods"

# ------------------------------------------------------------------ 1. mod manager
$sdkInstalled = (Test-Path (Join-Path $Win32 "Plugins\pyunrealsdk.dll")) -and (Test-Path (Join-Path $SdkMods "mods_base.sdkmod"))
if ($sdkInstalled -and -not $ReinstallSdk) {
    Say "Step 1 of 5: the mod manager is already installed. Leaving it as it is."
} elseif ($CheckOnly) {
    Say "Step 1 of 5: would download and install the mod manager $SdkVersion."
} else {
    Say "Step 1 of 5: installing the mod manager $SdkVersion."
    $zip = $SdkZip
    if (-not $zip) {
        $zip = Join-Path $env:TEMP "willow2-sdk-$SdkVersion.zip"
        Say "Downloading the mod manager, about 13 megabytes."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $SdkUrl -OutFile $zip -UseBasicParsing
        } catch { Fail "the mod manager couldn't be downloaded: $($_.Exception.Message)" }
    }
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $SdkSha256) { Fail "the mod manager download doesn't match the expected file. Nothing was installed." }
    Say "Download checked. Extracting into the game folder."
    try { Expand-Archive -Path $zip -DestinationPath $GameDir -Force }
    catch { Fail "couldn't extract the mod manager into the game folder: $($_.Exception.Message). If the game is under Program Files, try running Install.cmd as administrator." }
    if (-not $SdkZip) { Remove-Item $zip -ErrorAction SilentlyContinue }
    Say "Mod manager installed."
}

# ------------------------------------------------------------------ 2 and 3. prerequisites
function Test-VcRedistX86 {
    foreach ($k in "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x86",
                   "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86") {
        try { if ((Get-ItemProperty $k -ErrorAction Stop).Installed -eq 1) { return $true } } catch {}
    }
    return $false
}

function Find-Python64 {
    $override = Join-Path $SdkMods "bl2_access\helper\python_path.txt"
    if (Test-Path $override) { $p = (Get-Content $override -Raw).Trim().Trim('"'); if (Test-Path $p) { return $p } }
    $roots = @((Join-Path $env:LOCALAPPDATA "Programs\Python"), $env:ProgramW6432, "C:\")
    foreach ($r in $roots) {
        if (-not $r -or -not (Test-Path $r)) { continue }
        $hit = Get-ChildItem -Path $r -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike "*-32" -and (Test-Path (Join-Path $_.FullName "pythonw.exe")) } |
            Select-Object -First 1
        if ($hit) { return (Join-Path $hit.FullName "pythonw.exe") }
    }
    return $null
}

if ($SkipPrerequisites) {
    Say "Steps 2 and 3: skipped (prerequisite checks turned off)."
} else {
    if (Test-VcRedistX86) {
        Say "Step 2 of 5: the Visual C plus plus x86 runtime is installed."
    } elseif ($CheckOnly) {
        Say "Step 2 of 5: the Visual C plus plus x86 runtime is missing; would offer to install it."
    } elseif (Ask "Step 2 of 5: the mod manager needs the Microsoft Visual C plus plus x86 runtime, which isn't installed. Download it from Microsoft and install it now? Windows will ask for permission.") {
        $vc = Join-Path $env:TEMP "vc_redist.x86.exe"
        try {
            Invoke-WebRequest -Uri $VcRedistUrl -OutFile $vc -UseBasicParsing
            $sig = Get-AuthenticodeSignature $vc
            if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Microsoft Corporation") {
                Fail "the Visual C plus plus download isn't signed by Microsoft. Nothing was run."
            }
            Start-Process -FilePath $vc -ArgumentList "/install", "/quiet", "/norestart" -Verb RunAs -Wait
            Say "Visual C plus plus runtime installed."
        } catch { Say "The Visual C plus plus runtime couldn't be installed: $($_.Exception.Message). You can install it later from Microsoft." }
        Remove-Item $vc -ErrorAction SilentlyContinue
    } else {
        Say "Skipped. If the mod manager doesn't start, install the Visual C plus plus x86 runtime from Microsoft."
    }

    $py = Find-Python64
    if ($py) {
        Say "Step 3 of 5: found 64-bit Python for screen reader speech: $py"
    } elseif ($CheckOnly) {
        Say "Step 3 of 5: no 64-bit Python found; would offer to install it."
    } else {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget -and (Ask "Step 3 of 5: speech through Prism needs a 64-bit Python, which wasn't found. Install Python 3.12 for your user account with winget now?")) {
            & winget install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
            if (Find-Python64) { Say "Python installed." } else { Say "Python didn't install. You can install 64-bit Python from python.org later." }
        } else {
            Say "No 64-bit Python. Install it from python.org (64-bit) for screen reader speech through Prism."
        }
    }
}

# ------------------------------------------------------------------ 4. the mod
$dest = Join-Path $SdkMods "bl2_access"
if ($CheckOnly) {
    Say ("Step 4 of 5: would " + $(if (Test-Path $dest) { "update" } else { "install" }) + " Borderlands Access in $dest. Your mod settings would be kept.")
} else {
    Say "Step 4 of 5: copying Borderlands Access $ModVersion into the game."
    try {
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        # Copy everything from the package except logs; files the mod writes while you play
        # (logs, learned tab names, python_path.txt) are left in place.
        Get-ChildItem -Path $ModSource -Recurse -File | Where-Object {
            $_.FullName -notmatch "\\logs\\" -and $_.FullName -notmatch "\\maps\\" -and $_.FullName -notmatch "__pycache__"
        } | ForEach-Object {
            $rel = $_.FullName.Substring($ModSource.Length).TrimStart("\")
            $target = Join-Path $dest $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
            Copy-Item $_.FullName $target -Force
        }
    } catch { Fail "couldn't copy the mod into the game folder: $($_.Exception.Message). If the game is under Program Files, try running Install.cmd as administrator." }
    Say "Borderlands Access installed."
}

# ------------------------------------------------------------------ 5. skip the 2K launcher
$skip = Join-Path $ModSource "skip_launcher.ps1"
if ($SkipLauncherFix) {
    Say "Step 5 of 5: skipped (launcher fix turned off)."
} elseif ($CheckOnly) {
    Say "Step 5 of 5: would set Steam to skip the 2K launcher (closing and reopening Steam)."
} elseif (Ask "Step 5 of 5: the 2K launcher that opens before the game isn't accessible. Set Steam to skip it? This closes Steam and opens it again.") {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $skip -NoVoice
} else {
    Say "Skipped. You can run skip_launcher.ps1 from the mod folder later."
}

Say ""
if ($CheckOnly) {
    Say "Check finished. Nothing was changed."
} else {
    Say "All done. Start NVDA, then start Borderlands 2 from Steam. You should hear: Borderlands Access loaded."
    Say "In the game, press your modifier button three times quickly for the accessibility settings. The modifier is Back unless you change it."
}
if (-not $Yes) { Read-Host "Press Enter to close" | Out-Null }
