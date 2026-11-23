# Makes Steam start Borderlands 2 straight into the game, skipping the inaccessible 2K launcher.
# Launching through Steam keeps Steam Input, so the controller still works.
# It closes Steam, adds the launch option -nolauncher to Borderlands 2, then reopens Steam.
# Usage: powershell -ExecutionPolicy Bypass -File skip_launcher.ps1 [-ConfigPath <file>] [-NoRestart] [-NoVoice]
param([string]$ConfigPath = "", [switch]$NoRestart, [switch]$NoVoice)

Add-Type -AssemblyName System.Speech -ErrorAction SilentlyContinue
function Say($t) {
    Write-Host $t
    if ($NoVoice) { return }  # the installer's console is already read by the screen reader
    try { (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($t) } catch {}
}

$steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction SilentlyContinue).SteamPath
if (-not $steam) { $steam = "C:\Program Files (x86)\Steam" }
$steam = $steam -replace "/", "\"
$appId = "49520"

if (-not $ConfigPath) {
    Get-Process Launcher, Borderlands2 -ErrorAction SilentlyContinue | Stop-Process -Force
    if (Get-Process steam -ErrorAction SilentlyContinue) {
        Say "Closing Steam."
        & "$steam\steam.exe" -shutdown
        $n = 0
        while ((Get-Process steam -ErrorAction SilentlyContinue) -and $n -lt 60) { Start-Sleep 1; $n++ }
        if (Get-Process steam -ErrorAction SilentlyContinue) { Say "Steam did not close. Nothing was changed."; exit 1 }
    }
    $files = Get-ChildItem "$steam\userdata\*\config\localconfig.vdf" -ErrorAction SilentlyContinue
} else {
    $files = @(Get-Item $ConfigPath)
}

$done = 0
foreach ($f in $files) {
    $text = [IO.File]::ReadAllText($f.FullName)
    # The per-game block: "49520" { ... } inside "apps".
    $m = [regex]::Match($text, '(?s)"apps"\s*\{.*?\n(\s*)"' + $appId + '"\s*\{')
    if (-not $m.Success) { continue }
    $start = $m.Index + $m.Length
    # Find the end of this game's block so we only touch its own LaunchOptions line.
    $depth = 1; $i = $start
    while ($i -lt $text.Length -and $depth -gt 0) {
        if ($text[$i] -eq '{') { $depth++ } elseif ($text[$i] -eq '}') { $depth-- }
        $i++
    }
    $block = $text.Substring($start, $i - 1 - $start)
    $indent = $m.Groups[1].Value + "`t"
    $lo = [regex]::Match($block, '(?m)^(\s*)"LaunchOptions"\s*"([^"]*)"')
    if ($lo.Success) {
        if ($lo.Groups[2].Value -match '(?i)-nolauncher') { $done++; continue }
        $newVal = ($lo.Groups[2].Value + " -nolauncher").Trim()
        $block = $block.Remove($lo.Index, $lo.Length).Insert($lo.Index, $lo.Groups[1].Value + '"LaunchOptions"' + "`t`t" + '"' + $newVal + '"')
    } else {
        $block = "`n" + $indent + '"LaunchOptions"' + "`t`t" + '"-nolauncher"' + $block
    }
    Copy-Item $f.FullName ($f.FullName + ".bl2access.bak") -Force
    $text = $text.Substring(0, $start) + $block + $text.Substring($i - 1)
    [IO.File]::WriteAllText($f.FullName, $text)
    $done++
}

if ($done -gt 0) { Say "Done. Borderlands 2 will now skip the launcher when started from Steam." }
else { Say "Could not find Borderlands 2 in the Steam settings. Start the game from Steam once, then run this again." }

if (-not $ConfigPath -and -not $NoRestart) { Start-Process "$steam\steam.exe" }
