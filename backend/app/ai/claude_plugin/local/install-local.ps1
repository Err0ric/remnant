# Install this hooks plugin for your own user on this one machine, to test it.
#
# Run it from the unzipped plugin folder, in Windows PowerShell or PowerShell 7:
#   powershell -ExecutionPolicy Bypass -File .\install-local.ps1
#
# It copies this folder into a local marketplace (@MARKETPLACE@) under %LOCALAPPDATA%,
# registers that marketplace, installs the plugin for your user, and lists your plugins.
# Running it again replaces the earlier copy. Needs the Claude Code CLI (claude) on PATH:
# the desktop app's Code tab cannot run /plugin, so install from a terminal.
# To remove it: claude plugin marketplace remove @MARKETPLACE@

$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$Market = '@MARKETPLACE@'
$Dest = Join-Path $env:LOCALAPPDATA $Market

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host 'The Claude Code CLI (claude) is not on PATH. Install it, then run this again.'
    exit 1
}
$Manifest = Join-Path $Here '.claude-plugin\plugin.json'
if (-not (Test-Path -LiteralPath $Manifest)) {
    Write-Host 'No .claude-plugin\plugin.json here: run this from the unzipped plugin folder.'
    exit 1
}
$Name = (Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json).name

# A fresh copy each time: removing the marketplace also uninstalls the earlier copy.
$ErrorActionPreference = 'Continue'
& claude plugin marketplace remove $Market *> $null
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Dest) { Remove-Item -LiteralPath $Dest -Recurse -Force }
$PluginDir = Join-Path $Dest ('plugins\' + $Name)
New-Item -ItemType Directory -Force -Path (Join-Path $Dest '.claude-plugin') | Out-Null
New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
Get-ChildItem -LiteralPath $Here -Force |
    Where-Object { $_.Name -notlike 'install-local.*' } |
    Copy-Item -Destination $PluginDir -Recurse -Force

$Market_ = [ordered]@{
    name    = $Market
    owner   = [ordered]@{ name = 'Local test install' }
    plugins = @([ordered]@{
        name        = $Name
        source      = './plugins/' + $Name
        description = 'Observe-only Claude Code hooks, installed on this machine for testing'
    })
}
$Json = $Market_ | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Join-Path $Dest '.claude-plugin\marketplace.json'), $Json)

& claude plugin marketplace add $Dest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& claude plugin install "$Name@$Market" --scope user
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& claude plugin list
