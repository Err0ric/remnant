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
#
# Check a machine instead:
#   powershell -ExecutionPolicy Bypass -File .\install-local.ps1 -Doctor
# It reads the config (the machine file, else this folder's), checks the server answers,
# sends one test record with the token (marked as a test: no person, no machine), looks
# for the plugin in `claude plugin list`, and prints the hook's last status. It prints a
# pass or fail per check and never prints the token.
param([switch]$Doctor)

$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$Market = '@MARKETPLACE@'
$Dest = Join-Path $env:LOCALAPPDATA $Market

function Invoke-Doctor {
    $script:failed = $false
    function Pass([string]$m) { Write-Host "PASS  $m" }
    function Fail([string]$m) { Write-Host "FAIL  $m"; $script:failed = $true }
    function Note([string]$m) { Write-Host "INFO  $m" }
    $conf = Join-Path $env:ProgramData 'siem-claude-hooks\hooks.conf'
    if (-not (Test-Path -LiteralPath $conf)) { $conf = Join-Path $Here 'config' }
    $c = @{}
    if (Test-Path -LiteralPath $conf) {
        foreach ($line in [System.IO.File]::ReadAllLines($conf)) {
            $i = $line.IndexOf('=')
            if ($i -gt 0) { $c[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim() }
        }
        Pass "Config found: $conf"
    } else { Fail "No config: neither the machine file nor $Here\config" }
    $url = $c['REMNANT_URL']; $token = $c['REMNANT_TOKEN']
    if ($url) { Pass "Server: $url" } else { Fail 'The config names no server (REMNANT_URL)' }
    if ($token) {
        Pass ("Token present: " + $token.Substring(0, [Math]::Min(8, $token.Length)) + '... (the rest is not shown)')
    } else { Fail 'The config has no token (REMNANT_TOKEN)' }
    if ($c['CA_FILE']) {
        $ca = $c['CA_FILE']
        if (-not [System.IO.Path]::IsPathRooted($ca)) { $ca = Join-Path $Here $ca }
        if (Test-Path -LiteralPath $ca) {
            Pass "Certificate file: $ca (the hook trusts it; this check uses Windows' own trust)"
        } else { Fail "Certificate file named in the config is missing: $ca" }
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if ($url) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "$($url.TrimEnd('/'))/api/health"
            if ($r.StatusCode -eq 200) { Pass "The server answers at $url" }
            else { Fail "The server answered $($r.StatusCode) at $url/api/health" }
        } catch {
            Fail "Cannot reach $url (network, proxy, DNS, or the certificate is not trusted by Windows): $($_.Exception.Message)"
        }
    }
    if ($url -and $token) {
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $body = '{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"claude-hooks"}}]},"scopeLogs":[{"scope":{"name":"claude-hooks"},"logRecords":[{"timeUnixNano":"' + $now + '000000000","body":{"stringValue":"claude_hooks.session_start"},"attributes":[{"key":"event_name","value":{"stringValue":"claude_hooks.session_start"}},{"key":"role","value":{"stringValue":"session"}},{"key":"session_id","value":{"stringValue":"doctor-' + $now + '"}},{"key":"plugin_variant","value":{"stringValue":"doctor"}},{"key":"test_record","value":{"stringValue":"true"}}]}]}]}]}'
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Method Post -ContentType 'application/json' `
                -Headers @{ Authorization = "Bearer $token" } -Body $body -Uri "$($url.TrimEnd('/'))/api/otlp/v1/logs"
            Pass "The token works: a test record was accepted (HTTP $($r.StatusCode))"
        } catch {
            $code = $null
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
            if ($code -eq 401) { Fail 'The server refused the token (HTTP 401): wrong, revoked, or its source is off' }
            elseif ($code) { Fail "The server answered HTTP $code to the test record" }
            else { Fail "The test record could not be sent: $($_.Exception.Message)" }
        }
    }
    $manifest = Join-Path $Here '.claude-plugin\plugin.json'
    $name = ''
    if (Test-Path -LiteralPath $manifest) { $name = (Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json).name }
    if (Get-Command claude -ErrorAction SilentlyContinue) {
        $list = (& claude plugin list 2>$null | Out-String)
        if ($name -and $list -match [regex]::Escape($name)) { Pass "Claude Code lists the plugin ($name)" }
        else { Fail "Claude Code does not list $($name): install it (install-local.ps1) and restart Claude" }
    } else { Note 'The Claude Code CLI is not on PATH: cannot check which plugins are installed' }
    $candidates = @()
    if ($env:CLAUDE_PLUGIN_DATA) { $candidates += (Join-Path $env:CLAUDE_PLUGIN_DATA 'status') }
    $candidates += @(Get-ChildItem -Path (Join-Path $env:USERPROFILE '.claude\plugins\data') -Filter status -Recurse -Depth 2 -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    $candidates += (Join-Path $env:LOCALAPPDATA 'siem-claude-hooks\status')
    $found = $false
    foreach ($f in $candidates) {
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $found = $true
        Pass "The hook has run on this machine; its last status ($f):"
        Get-Content -LiteralPath $f | ForEach-Object { Write-Host "        $_" }
    }
    if (-not $found) {
        Fail 'No status file: the hook has not run for this user since version 2.2.0 (start a Claude Code session, then check again)'
    }
    if ($script:failed) { Write-Host 'Some checks failed.'; return 1 }
    Write-Host 'All checks passed.'; return 0
}

if ($Doctor) {
    $ErrorActionPreference = 'Continue'
    exit (Invoke-Doctor)
}

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
