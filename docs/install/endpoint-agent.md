# Optional endpoint agent (OpenTelemetry Collector)

Use this when endpoints or servers have no log collector, or you want Windows security events from workstations. The agent is the official **OpenTelemetry Collector** (contrib build) with a configuration Remnant generates; Remnant ships no agent binary of its own (ADR-0017).

| | |
|---|---|
| Windows | Security, System, Application, Sysmon, PowerShell Operational, Defender. Read as event XML and parsed by the same Windows template as `.evtx` files |
| Linux | journald (sshd, sudo, PAM, systemd land in the Linux templates). Or `/var/log/auth.log` and friends if you prefer files |
| Optional | Host metrics (commented out in the config: many rows per host) |
| Health | Each agent group is a source: last received time, Overview, and **Alert if quiet** |

## 1. Create an agent group (Remnant admin)

**Sources > Add source**, for example `agents_workstations`, **Reads from: OpenTelemetry**, Parser **Automatic**. Copy the token. Then on the source's row, **Agent config: Windows** (or Linux) downloads the collector config. It contains no secret.

Use one group per kind of machine (workstations, servers, domain controllers), so a leaked token affects one group and the quiet alert means something.

## 2. Install on Windows (RMM tool, Intune, or GPO)

1. Install the OpenTelemetry Collector contrib MSI (`otelcol-contrib`, from the project's GitHub releases; check the signature).
2. Copy the config to `C:\Program Files\OpenTelemetry Collector\config.yaml`.
3. Create `C:\ProgramData\Remnant\token.txt` with the token and **no trailing newline**:
   `Set-Content -Path C:\ProgramData\Remnant\token.txt -Value 'rmt_...' -NoNewline`
   Restrict it to SYSTEM and Administrators (`icacls C:\ProgramData\Remnant /inheritance:r /grant SYSTEM:F /grant Administrators:F`).
4. If Remnant uses its self-signed certificate, copy it to `C:\ProgramData\Remnant\remnant-ca.pem` (or delete the `tls` block when Remnant has a certificate Windows already trusts).
5. Restart the `otelcol-contrib` service.

Reading the Security log needs the service to run as LocalSystem (the MSI default).

## 3. Install on Linux

```bash
sudo dpkg -i otelcol-contrib_<version>_linux_amd64.deb      # or the .rpm
sudo install -d -m 0750 -o root -g otelcol-contrib /etc/remnant
printf %s 'rmt_...' | sudo tee /etc/remnant/token >/dev/null
sudo chown root:otelcol-contrib /etc/remnant/token && sudo chmod 0640 /etc/remnant/token
sudo cp remnant-agent-<group>-linux.yaml /etc/otelcol-contrib/config.yaml
sudo usermod -aG systemd-journal otelcol-contrib            # read the journal
sudo systemctl restart otelcol-contrib
```

## 4. Check it

Within a minute the source shows **Reading** and a received time. Search `source:agents_workstations` and look at **Fields > Host**: one entry per machine sending.

Per-host check-in (save it and put it on a schedule to list hosts silent for a day):

```sql
SELECT device_hostname, max(time_observed) AS last_seen
FROM events WHERE source_id = 'agents_workstations'
GROUP BY 1 ORDER BY 2
```

## MCP inventory on the same machines

The collector cannot run scripts. Run `scripts/endpoint/mcp-inventory.ps1` (Windows) or `mcp_inventory.py` (Linux, macOS) daily from an RMM tool, Intune, or cron, with `-Endpoint` / `--endpoint` and the same token file. See [mcp-inventory.md](mcp-inventory.md).

## What `raw` holds for agent events

- File lines: exactly as written.
- Windows events: the event XML as JSON (the same shape as `.evtx` files read directly).
- journald: an RFC 5424 line built from the journal entry (time, host, program, PID, priority, message).
