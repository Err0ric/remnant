<#
.SYNOPSIS
  Lists the MCP servers configured on this Windows machine, one JSON line per server
  (ADR-0015 row 6). Names only: never arguments, environment variables, headers, or URLs.

.DESCRIPTION
  Reads Claude Desktop, Claude Code, Cursor, VS Code, and Windsurf MCP configuration for the
  current user, or for every profile under C:\Users when run elevated (for example as SYSTEM
  from an RMM tool, Intune, or a scheduled task). Same output as mcp_inventory.py.

.EXAMPLE
  .\mcp-inventory.ps1                                   # JSON lines to stdout
  .\mcp-inventory.ps1 -OutFile C:\ProgramData\Remnant\mcp-inventory.jsonl
  .\mcp-inventory.ps1 -Endpoint https://siem.example.internal:8080/api/otlp -TokenFile C:\ProgramData\Remnant\mcp.token

.NOTES
  Windows PowerShell 5.1 or PowerShell 7. The Remnant certificate must be trusted by Windows
  (deploy your CA, or Remnant's self-signed certificate, to Trusted Root by GPO or Intune).
#>
[CmdletBinding()]
param(
    [string]$OutFile,
    [string]$Endpoint,
    [string]$TokenFile
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

$Launchers = @('npx', 'npx.cmd', 'uvx', 'uvx.exe', 'bunx', 'pnpm', 'pipx', 'dlx')
$PackagePattern = '^(@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*(@[\w.^~<>=*-]+)?$'
$Locations = @(
    @{ Client = 'claude_desktop'; Path = 'AppData\Roaming\Claude\claude_desktop_config.json'; Key = 'mcpServers' },
    @{ Client = 'vscode';         Path = 'AppData\Roaming\Code\User\mcp.json';                  Key = 'servers' },
    @{ Client = 'claude_code';    Path = '.claude.json';                                         Key = 'mcpServers' },
    @{ Client = 'cursor';         Path = '.cursor\mcp.json';                                     Key = 'mcpServers' },
    @{ Client = 'windsurf';       Path = '.codeium\windsurf\mcp_config.json';                    Key = 'mcpServers' }
)

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Homes {
    if (-not (Test-Admin)) { return ,@(@{ User = $env:USERNAME; Home = $env:USERPROFILE }) }
    $skip = @('Public', 'Default', 'Default User', 'All Users')
    Get-ChildItem -Path (Split-Path $env:USERPROFILE -Parent) -Directory -ErrorAction SilentlyContinue |
        Where-Object { $skip -notcontains $_.Name -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } |
        ForEach-Object { @{ User = $_.Name; Home = $_.FullName } }
}

function Read-Config([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $null }
    if ($item.Length -gt 5MB) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Get-Prop($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Get-ServerMaps([string]$Client, $Doc, [string]$Key) {
    $maps = @()
    $m = Get-Prop $Doc $Key
    if ($m -is [psobject]) { $maps += , @('user', $m) }
    if ($Client -eq 'vscode') {
        $s = Get-Prop (Get-Prop $Doc 'mcp') 'servers'
        if ($s -is [psobject]) { $maps += , @('user', $s) }
    }
    if ($Client -eq 'claude_code') {
        $projects = Get-Prop $Doc 'projects'
        if ($projects -is [psobject]) {
            foreach ($proj in $projects.PSObject.Properties) {
                $s = Get-Prop $proj.Value 'mcpServers'
                if ($s -is [psobject]) { $maps += , @('project', $s) }
            }
        }
    }
    return $maps
}

function Get-PackageName([string]$Spec) {
    $at = $Spec.IndexOf('@', 1)
    if ($at -lt 0) { return $Spec }
    return $Spec.Substring(0, $at)
}

function Get-ServerInfo($Entry) {
    $url = Get-Prop $Entry 'url'
    if (-not $url) { $url = Get-Prop $Entry 'serverUrl' }
    if ($url -is [string] -and $url) {
        $hostName = $null
        try { $hostName = ([Uri]$url).Host } catch { }
        $type = Get-Prop $Entry 'type'
        if (@('http', 'sse', 'streamable-http') -notcontains $type) { $type = 'http' }
        return [ordered]@{ transport = $type; command = $null; package = $null; url_host = $hostName }
    }
    $command = Get-Prop $Entry 'command'
    $name = $null
    if ($command -is [string] -and $command) { $name = Split-Path $command -Leaf }
    $package = $null
    $argList = Get-Prop $Entry 'args'
    if ($name -and ($Launchers -contains $name.ToLower()) -and $argList) {
        foreach ($a in $argList) {
            if ($a -is [string] -and -not $a.StartsWith('-') -and $a -match $PackagePattern) {
                $package = Get-PackageName $a
                break
            }
        }
    }
    return [ordered]@{ transport = 'stdio'; command = $name; package = $package; url_host = $null }
}

$hostName = [Environment]::MachineName
$now = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
$records = New-Object System.Collections.Generic.List[object]
foreach ($h in Get-Homes) {
    foreach ($loc in $Locations) {
        $path = Join-Path $h.Home $loc.Path
        $doc = Read-Config $path
        if ($null -eq $doc) { continue }
        $seen = @{}
        foreach ($pair in (Get-ServerMaps $loc.Client $doc $loc.Key)) {
            $scope = $pair[0]
            foreach ($srv in $pair[1].PSObject.Properties) {
                $k = "$scope/$($srv.Name)"
                if ($seen.ContainsKey($k)) { continue }
                $seen[$k] = $true
                $rec = [ordered]@{
                    event   = 'mcp_inventory'
                    time    = $now
                    host    = $hostName
                    os_user = $h.User
                    client  = $loc.Client
                    server  = $srv.Name.Substring(0, [Math]::Min(200, $srv.Name.Length))
                    scope   = $scope
                    config  = $path
                }
                foreach ($e in (Get-ServerInfo $srv.Value).GetEnumerator()) { $rec[$e.Key] = $e.Value }
                $records.Add($rec)
            }
        }
    }
}

if ($Endpoint) {
    if (-not $TokenFile) { throw '-Endpoint needs -TokenFile (a token on the command line shows in process lists)' }
    if (-not $Endpoint.StartsWith('https://')) { throw 'The endpoint must use https' }
    $token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
    $nanos = [string](([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) * 1000000)
    for ($i = 0; $i -lt $records.Count; $i += 500) {
        $batch = $records.GetRange($i, [Math]::Min(500, $records.Count - $i))
        $logRecords = foreach ($r in $batch) {
            $attrs = @(@{ key = 'event.name'; value = @{ stringValue = 'mcp_inventory' } })
            foreach ($e in $r.GetEnumerator()) {
                if (@('event', 'time') -contains $e.Key -or $null -eq $e.Value) { continue }
                $attrs += @{ key = $e.Key; value = @{ stringValue = [string]$e.Value } }
            }
            @{ timeUnixNano = $nanos; attributes = $attrs }
        }
        $body = @{
            resourceLogs = @(@{
                resource  = @{ attributes = @(
                    @{ key = 'service.name'; value = @{ stringValue = 'remnant-mcp-inventory' } },
                    @{ key = 'host.name'; value = @{ stringValue = $hostName } }) }
                scopeLogs = @(@{ logRecords = @($logRecords) })
            })
        } | ConvertTo-Json -Depth 12 -Compress
        Invoke-RestMethod -Method Post -Uri ($Endpoint.TrimEnd('/') + '/v1/logs') -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
            -ContentType 'application/json' -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 30 | Out-Null
    }
    Write-Host "sent $($records.Count) servers"
    exit 0
}

$lines = foreach ($r in $records) { $r | ConvertTo-Json -Depth 4 -Compress }
if ($OutFile) {
    if ($lines) { Add-Content -LiteralPath $OutFile -Value $lines -Encoding UTF8 }
} else {
    $lines
}
