# Observe-only hook for Claude Code on Windows (ADR-0026, amendment 2026-10-29).
# Windows PowerShell 5.1, nothing to install. One OTLP log record per event, sent to the
# one server named in the managed config.
#
# What it never does: block, change, or delay anything. It runs in the background
# (async in hooks.json), waits at most about 2 seconds for the server, ignores every
# error, prints only {} (never the server's answer), and always exits 0.
#
# Sends by default: the event, time, session id, Claude account email (and where it came
# from), OS user, machine, tool name, the MCP server and tool, the file path or web host
# or program name a tool touched, sizes, and SHA-256 hashes of the prompt and tool input.
# Prompt text, tool input, tool output, and tool errors are sent only when the config
# says SEND_CONTENT=1, each cut to its first and last 4 KB.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Finish {
    [Console]::Out.Write("{}`n")
    exit 0
}

function Get-Field($o, [string]$name) {
    if ($null -eq $o) { return $null }
    if ($o -is [System.Collections.IDictionary]) {
        # Keys works for a Hashtable and for JavaScriptSerializer's generic Dictionary,
        # whose Contains is not callable from Windows PowerShell 5.1.
        if ($o.Keys -contains $name) { return $o[$name] }
        return $null
    }
    $p = $o.PSObject.Properties[$name]
    if ($p) { return $p.Value }
    return $null
}

# JSON from a file or a hook: ConvertFrom-Json first. It refuses objects with an
# empty-string key, so then JavaScriptSerializer with a raised limit on Windows
# PowerShell 5.1, or -AsHashtable on PowerShell 6 and later.
function Read-Json([string]$text) {
    try { return ($text | ConvertFrom-Json) } catch { }
    if ($PSVersionTable.PSVersion.Major -ge 6) { return ($text | ConvertFrom-Json -AsHashtable) }
    Add-Type -AssemblyName System.Web.Extensions
    $ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
    $ser.MaxJsonLength = [int]::MaxValue
    $ser.RecursionLimit = 256
    return $ser.DeserializeObject($text)
}

function To-Json($o) {
    if ($null -eq $o) { return '' }
    if ($o -is [string]) { return $o }
    return (ConvertTo-Json -InputObject $o -Depth 20 -Compress)
}

# Content is cut to its first and last 4 KB.
function Limit([string]$s) {
    if ($null -eq $s -or $s.Length -le 8192) { return $s }
    $a = 4096
    if ([char]::IsHighSurrogate($s[$a - 1])) { $a-- }
    $b = $s.Length - 4096
    if ([char]::IsLowSurrogate($s[$b])) { $b++ }
    return $s.Substring(0, $a) + "`n[...]`n" + $s.Substring($b)
}

function Sha256([string]$s) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($s))
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

# Config files are key=value data, read and never run.
function Read-Conf([string]$path) {
    $c = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($path)) {
        $i = $line.IndexOf('=')
        if ($i -gt 0) { $c[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim() }
    }
    return $c
}

try {
    # Sessions that belong to another plugin: Cowork has its own, macOS and Linux theirs.
    if ("$env:CLAUDE_CODE_IS_COWORK" -match '^(?i:true|1)$') { Finish }
    if ($env:OS -ne 'Windows_NT') { Finish }

    # --- Config: the machine-wide file wins; the plugin's own copy is the fallback. ---
    # When the machine file exists, the plugin's copy (in the user's folder) is not read.
    $conf = $null
    $machine = $false
    if ($env:ProgramData) {
        $machineConf = Join-Path $env:ProgramData 'siem-claude-hooks\hooks.conf'
        if ([System.IO.File]::Exists($machineConf)) {
            $conf = Read-Conf $machineConf
            $machine = $true
        }
    }
    if (-not $machine) {
        $bundled = Join-Path (Split-Path -Parent $PSScriptRoot) 'config'
        if (-not [System.IO.File]::Exists($bundled)) { Finish }
        $conf = Read-Conf $bundled
    }
    $url = $conf['REMNANT_URL']
    $token = $conf['REMNANT_TOKEN']
    # Only the machine file can let the environment name the server (testing a build).
    if ($machine -and $conf['DEV_ENV_OVERRIDE'] -eq '1') {
        if ($env:REMNANT_URL) { $url = $env:REMNANT_URL }
        if ($env:REMNANT_TOKEN) { $token = $env:REMNANT_TOKEN }
    }
    if (-not $url -or -not $token) { Finish }
    $sendContent = ($conf['SEND_CONTENT'] -eq '1')

    $data = $env:CLAUDE_PLUGIN_DATA
    if (-not $data) { $data = Join-Path $env:LOCALAPPDATA 'siem-claude-hooks' }
    [void](New-Item -ItemType Directory -Force -Path $data)

    # The hook input, capped at 1 MB.
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    $reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
    $buf = New-Object char[] 1048576
    $n = $reader.ReadBlock($buf, 0, $buf.Length)
    $hook = Read-Json (New-Object string($buf, 0, $n))

    # --- The Claude account: managed config, then CLAUDE_CODE_USER_EMAIL, then the
    # signed-in account in .claude.json (oauthAccount.emailAddress only). ---------------
    $email = ''
    $accountFrom = ''
    if ($machine -and $conf['CLAUDE_EMAIL']) {
        $email = $conf['CLAUDE_EMAIL']; $accountFrom = 'managed'
    } elseif ($env:CLAUDE_CODE_USER_EMAIL) {
        $email = $env:CLAUDE_CODE_USER_EMAIL; $accountFrom = 'env'
    } else {
        $dir = $env:CLAUDE_CONFIG_DIR
        if (-not $dir) { $dir = $env:USERPROFILE }
        if (-not $dir) { $dir = $HOME }
        $json = Join-Path $dir '.claude.json'
        $cache = Join-Path $data 'account'
        $fileInfo = New-Object System.IO.FileInfo($json)
        $cacheInfo = New-Object System.IO.FileInfo($cache)
        if ($fileInfo.Exists) {
            if ($cacheInfo.Exists -and $cacheInfo.LastWriteTimeUtc -ge $fileInfo.LastWriteTimeUtc) {
                $email = ([System.IO.File]::ReadAllLines($cache) | Select-Object -First 1)
            } elseif ($fileInfo.Length -le 16MB) {
                try {
                    $cfg = Read-Json ([System.IO.File]::ReadAllText($json, [System.Text.Encoding]::UTF8))
                    $email = [string](Get-Field (Get-Field $cfg 'oauthAccount') 'emailAddress')
                } catch { $email = '' }
                [System.IO.File]::WriteAllText($cache, "$email`n")
            }
            if ($email -match '@') { $accountFrom = 'claude_json' } else { $email = '' }
        }
    }
    if ($email -notmatch '^[A-Za-z0-9.@_+-]+$') { $email = ''; $accountFrom = '' }
    $osUser = [Environment]::UserName

    # Pilot mode: when PILOT_USERS lists people, only they send.
    $pilot = "$($conf['PILOT_USERS'])"
    if ($pilot.Trim()) {
        $list = @($pilot.ToLowerInvariant() -split '[\s,]+' | Where-Object { $_ })
        $me = $email.ToLowerInvariant()
        $me2 = "$osUser".ToLowerInvariant()
        if (-not (($me -and ($list -contains $me)) -or ($me2 -and ($list -contains $me2)))) { Finish }
    }

    $event = [string](Get-Field $hook 'hook_event_name')
    $map = @{
        'SessionStart'       = @('session_start', 'session')
        'UserPromptSubmit'   = @('user_prompt_submit', 'user')
        'PreToolUse'         = @('pre_tool_use', 'tool_call')
        'PostToolUse'        = @('post_tool_use', 'tool_result')
        'PostToolUseFailure' = @('post_tool_use_failure', 'tool_result')
        'Stop'               = @('stop', 'turn')
        'SessionEnd'         = @('session_end', 'session')
    }
    if (-not $map.ContainsKey($event)) { Finish }
    $name = $map[$event][0]
    $role = $map[$event][1]

    $tool = [string](Get-Field $hook 'tool_name')
    $toolIn = Get-Field $hook 'tool_input'
    $toolInText = To-Json $toolIn
    $toolOutText = To-Json (Get-Field $hook 'tool_response')
    $errorText = [string](Get-Field $hook 'error')
    $prompt = ''
    if ($event -eq 'UserPromptSubmit') { $prompt = [string](Get-Field $hook 'prompt') }

    $path = ''
    foreach ($k in 'file_path', 'notebook_path', 'path') {
        $v = Get-Field $toolIn $k
        if ($v -is [string] -and $v) { $path = $v; break }
    }
    $webHost = ''
    $u = Get-Field $toolIn 'url'
    if ($u -is [string]) {
        $parsed = $null
        if ([Uri]::TryCreate($u, [UriKind]::Absolute, [ref]$parsed) -and $parsed.Host -match '^[A-Za-z0-9.-]+$') {
            $webHost = $parsed.Host
        }
    }
    $program = ''
    $cmd = Get-Field $toolIn 'command'
    if ($cmd -is [string]) {
        $first = (($cmd -replace '["'']', '').TrimStart() -split '[\s;|&<>(]')[0]
        $first = ($first -split '[\\/]')[-1]
        if ($first -match '^[A-Za-z0-9._+-]+$') { $program = $first }
    }
    $mcpServer = ''; $mcpTool = ''
    if ($tool -like 'mcp__*') {
        $parts = $tool -split '__'
        if ($parts.Count -ge 3) { $mcpServer = $parts[1]; $mcpTool = $parts[2] }
    }

    function Clip([string]$s, [int]$max) {
        if ($null -eq $s) { return '' }
        if ($s.Length -le $max) { return $s }
        return $s.Substring(0, $max)
    }

    $attrs = New-Object System.Collections.ArrayList
    function Add-Attr([string]$key, $value) {
        if ($null -ne $value -and "$value" -ne '') {
            [void]$attrs.Add(@{ key = $key; value = @{ stringValue = "$value" } })
        }
    }
    function Add-Num([string]$key, [long]$value) {
        if ($value -ne 0) { [void]$attrs.Add(@{ key = $key; value = @{ intValue = "$value" } }) }
    }

    # Records this machine could not send earlier: counted, and reported with this one.
    $droppedFile = Join-Path $data 'dropped'
    $pending = $null
    $dropped = 0
    $droppedInfo = New-Object System.IO.FileInfo($droppedFile)
    if ($droppedInfo.Exists -and $droppedInfo.Length -gt 0) {
        $candidate = Join-Path $data ("dropped.$PID")
        try {
            [System.IO.File]::Move($droppedFile, $candidate)
            $pending = $candidate
            $dropped = (New-Object System.IO.FileInfo($pending)).Length
        } catch { $pending = $null }
    }

    Add-Attr 'event_name' "claude_hooks.$name"
    Add-Attr 'role' $role
    Add-Attr 'plugin_variant' 'windows'
    Add-Attr 'session_id' (Clip ([string](Get-Field $hook 'session_id')) 512)
    Add-Attr 'session_source' (Clip ([string](Get-Field $hook 'source')) 64)
    Add-Attr 'end_reason' (Clip ([string](Get-Field $hook 'reason')) 64)
    Add-Attr 'claude_account_email' $email
    Add-Attr 'account_from' $accountFrom
    Add-Attr 'os_user' $osUser
    Add-Attr 'cwd' (Clip ([string](Get-Field $hook 'cwd')) 512)
    Add-Attr 'tool_name' (Clip $tool 512)
    Add-Attr 'mcp_server_name' (Clip $mcpServer 512)
    Add-Attr 'mcp_tool_name' (Clip $mcpTool 512)
    Add-Attr 'path' (Clip $path 512)
    Add-Attr 'web_host' $webHost
    Add-Attr 'program' $program
    if ($name -eq 'post_tool_use_failure') { Add-Attr 'outcome' 'failure' }
    if ($prompt) {
        Add-Attr 'prompt_sha256' (Sha256 $prompt)
        Add-Num 'prompt_chars' $prompt.Length
    }
    if ($toolInText) { Add-Attr 'tool_input_sha256' (Sha256 $toolInText) }
    Add-Num 'tool_input_chars' $toolInText.Length
    Add-Num 'tool_response_chars' $toolOutText.Length
    Add-Num 'error_chars' $errorText.Length
    Add-Num 'dropped_since_last' $dropped
    if ($sendContent) {
        Add-Attr 'prompt' (Limit $prompt)
        Add-Attr 'tool_input' (Limit $toolInText)
        Add-Attr 'tool_response' (Limit $toolOutText)
        Add-Attr 'tool_error' (Limit $errorText)
    }

    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $record = @{
        resourceLogs = @(@{
            resource  = @{ attributes = @(
                @{ key = 'service.name'; value = @{ stringValue = 'claude-hooks' } },
                @{ key = 'host.name'; value = @{ stringValue = [Environment]::MachineName } }
            ) }
            scopeLogs = @(@{
                scope      = @{ name = 'claude-hooks'; version = '2.0.0' }
                logRecords = @(@{
                    timeUnixNano = "$($now)000000000"
                    body         = @{ stringValue = "claude_hooks.$name" }
                    attributes   = $attrs.ToArray()
                })
            })
        })
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $record -Depth 12 -Compress))

    # One HTTP/1.1 POST over a direct connection: TLS 1.2, the host name always checked, and
    # with CA_FILE the server's chain must end at that CA. The certificate check runs on
    # this thread (SslStream, synchronous), which a PowerShell callback needs; a web
    # request's callback runs elsewhere and fails or deadlocks. There is no switch to skip
    # checking. Only the status line of the answer is read; its body never is.
    $ca = $conf['CA_FILE']
    # A certificate named without a folder is the one bundled in the plugin.
    if ($ca -and -not $machine -and -not [System.IO.Path]::IsPathRooted($ca)) {
        $ca = Join-Path (Split-Path -Parent $PSScriptRoot) $ca
    }
    $script:caCert = $null
    if ($ca -and [System.IO.File]::Exists($ca)) {
        $script:caCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ca)
    }
    $sent = $false
    $client = $null
    try {
        $target = [Uri]("$($url.TrimEnd('/'))/api/otlp/v1/logs")
        if ($target.Scheme -ne 'https' -and $target.Scheme -ne 'http') { throw 'scheme' }
        $client = New-Object System.Net.Sockets.TcpClient
        if (-not $client.ConnectAsync($target.Host, $target.Port).Wait(1000)) { throw 'connect' }
        $stream = $client.GetStream()
        $stream.ReadTimeout = 1000
        $stream.WriteTimeout = 1000
        if ($target.Scheme -eq 'https') {
            $check = {
                param($sender, $cert, $chain, $errors)
                if ($errors -eq [Net.Security.SslPolicyErrors]::None) { return $true }
                # A wrong host name still fails; only an unknown issuer is checked further.
                if ($null -eq $script:caCert -or
                    $errors -ne [Net.Security.SslPolicyErrors]::RemoteCertificateChainErrors) { return $false }
                $c = New-Object System.Security.Cryptography.X509Certificates.X509Chain
                $c.ChainPolicy.RevocationMode = 'NoCheck'
                $c.ChainPolicy.VerificationFlags = 'AllowUnknownCertificateAuthority'
                [void]$c.ChainPolicy.ExtraStore.Add($script:caCert)
                if (-not $c.Build((New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cert)))) { return $false }
                $root = $c.ChainElements[$c.ChainElements.Count - 1].Certificate
                return ($root.Thumbprint -eq $script:caCert.Thumbprint)
            }
            $ssl = New-Object System.Net.Security.SslStream($stream, $false, [System.Net.Security.RemoteCertificateValidationCallback]$check)
            $ssl.ReadTimeout = 1000
            $ssl.WriteTimeout = 1000
            $ssl.AuthenticateAsClient($target.Host, $null, [System.Security.Authentication.SslProtocols]::Tls12, $false)
            $stream = $ssl
        }
        $head = "POST $($target.PathAndQuery) HTTP/1.1`r`nHost: $($target.Authority)`r`n" +
            "Content-Type: application/json`r`nAuthorization: Bearer $token`r`n" +
            "Content-Length: $($bytes.Length)`r`nConnection: close`r`n`r`n"
        $headBytes = [System.Text.Encoding]::ASCII.GetBytes($head)
        $stream.Write($headBytes, 0, $headBytes.Length)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        # The status line only: "HTTP/1.1 200 OK".
        $line = New-Object System.Text.StringBuilder
        while ($line.Length -lt 64) {
            $b = $stream.ReadByte()
            if ($b -lt 0 -or $b -eq 10) { break }
            [void]$line.Append([char]$b)
        }
        $parts = $line.ToString().Split(' ')
        $code = 0
        if ($parts.Length -ge 2 -and [int]::TryParse($parts[1], [ref]$code)) {
            $sent = ($code -ge 200 -and $code -lt 300)
        }
    } catch { $sent = $false }
    if ($client) { $client.Close() }

    if ($sent) {
        if ($pending) { [System.IO.File]::Delete($pending) }
    } else {
        $old = ''
        if ($pending) { $old = [System.IO.File]::ReadAllText($pending); [System.IO.File]::Delete($pending) }
        [System.IO.File]::AppendAllText($droppedFile, $old + 'x')
    }
} catch { }
Finish
