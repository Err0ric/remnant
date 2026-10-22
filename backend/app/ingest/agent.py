"""OpenTelemetry Collector configuration for an agent group (ADR-0017 rows 2 and 3).

The config holds no secret: the ingest token is read from a file next to it at start-up
(`${file:...}`), so the config can sit in a deployment tool. Windows events are collected
as event XML (`raw: true`), which the receiver turns into the shape `windows_evtx` reads;
journald entries become RFC 5424 lines for the Linux templates (ADR-0017 row 4).
"""

from datetime import UTC, datetime
from typing import Literal

AgentOs = Literal["windows", "linux"]

WINDOWS_CHANNELS = (
    ("security", "Security"),
    ("system", "System"),
    ("application", "Application"),
    ("sysmon", "Microsoft-Windows-Sysmon/Operational"),
    ("powershell", "Microsoft-Windows-PowerShell/Operational"),
    ("defender", "Microsoft-Windows-Windows Defender/Operational"),
)


def paths(target: AgentOs, product: str) -> dict[str, str]:
    """Where the agent keeps its token, CA certificate, and retry queue on an endpoint."""
    if target == "windows":
        base = f"C:/ProgramData/{product}"
        return {
            "token": f"{base}/token.txt",
            "ca": f"{base}/{product.lower()}-ca.pem",
            "queue": f"{base}/queue",
        }
    name = product.lower()
    return {
        "token": f"/etc/{name}/token",
        "ca": f"/etc/{name}/{name}-ca.pem",
        "queue": f"/var/lib/{name}-agent/queue",
    }


def _q(text: str) -> str:
    """A YAML double-quoted scalar."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(
    target: AgentOs, endpoint: str, source_id: str, product: str, server_name: str | None = None
) -> str:
    p = paths(target, product)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    out = [
        f"# {product} agent: OpenTelemetry Collector configuration (ADR-0017)",
        f"# Agent group (OTLP source): {source_id}. Generated {stamp}.",
        "#",
        f"# 1. Put this group's ingest token in {p['token']} with no trailing newline,",
        "#    readable only by the collector's service account.",
        f"# 2. If {product} uses its self-signed certificate, copy it to {p['ca']};",
        "#    otherwise delete the tls block below.",
        "# 3. Install the OpenTelemetry Collector (contrib build) and start it with this file.",
        "",
        "receivers:",
    ]
    log_receivers: list[str] = []
    if target == "windows":
        for name, channel in WINDOWS_CHANNELS:
            out += [
                f"  windowseventlog/{name}:",
                f"    channel: {_q(channel)}",
                "    raw: true          # event XML; the server reads it like .evtx",
                "    start_at: end",
                "    storage: file_storage   # resume after a restart, no gap and no repeats",
            ]
            log_receivers.append(f"windowseventlog/{name}")
    else:
        out += [
            "  journald:",
            "    priority: info",
            "    start_at: end",
            "  # If rsyslog writes these files and journald is not persistent, use filelog",
            "  # instead of journald (both would read the same events twice):",
            "  # filelog:",
            "  #   include: [/var/log/auth.log, /var/log/secure, /var/log/syslog]",
            "  #   start_at: end",
            "  #   include_file_name: true",
            "  #   storage: file_storage",
        ]
        log_receivers.append("journald")
    out += [
        "  # Host metrics every minute; off by default (many rows per host).",
        "  # hostmetrics:",
        "  #   collection_interval: 60s",
        "  #   scrapers: { cpu: {}, memory: {}, disk: {}, filesystem: {}, network: {} }",
        "",
        "processors:",
        "  memory_limiter:",
        "    check_interval: 1s",
        "    limit_mib: 256",
        "  resourcedetection:",
        "    detectors: [system]",
        "    system:",
        "      hostname_sources: [os]",
        "  batch:",
        "    send_batch_size: 500",
        "    timeout: 5s",
        "",
        "extensions:",
        "  # Read positions and the sending queue live on disk: a laptop off the VPN or",
        "  # asleep keeps its events and sends them when it can reach the server again.",
        "  file_storage:",
        f"    directory: {_q(p['queue'])}",
        "    create_directory: true",
        "    compaction:",
        "      on_start: true",
        f"      directory: {_q(p['queue'])}",
        "",
        "exporters:",
        "  otlphttp/remnant:",
        f"    endpoint: {_q(endpoint)}",
        "    encoding: json",
        "    compression: gzip",
        "    headers:",
        f'      Authorization: "Bearer ${{file:{p["token"]}}}"',
        "    tls:",
        f"      ca_file: {_q(p['ca'])}",
        *(
            [
                "      # Agents connect by address; the certificate names the server:",
                f"      server_name_override: {_q(server_name)}",
            ]
            if server_name
            else [
                "      # Connecting by IP address to a certificate issued for a name? Set the",
                "      # name here (or download the config with ?server_name=...):",
                '      # server_name_override: "siem.example.internal"',
            ]
        ),
        "    retry_on_failure:",
        "      enabled: true",
        "      initial_interval: 5s",
        "      max_interval: 5m",
        "      max_elapsed_time: 0   # keep retrying: the queue holds events while offline",
        "    sending_queue:",
        "      enabled: true",
        "      storage: file_storage   # on disk, so a restart or reboot loses nothing",
        "      num_consumers: 2",
        "      queue_size: 20000      # batches; about a week of a typical laptop's events",
        "",
        "service:",
        "  extensions: [file_storage]",
        "  pipelines:",
        "    logs:",
        f"      receivers: [{', '.join(log_receivers)}]",
        "      processors: [memory_limiter, resourcedetection, batch]",
        "      exporters: [otlphttp/remnant]",
        "    # metrics:",
        "    #   receivers: [hostmetrics]",
        "    #   processors: [memory_limiter, resourcedetection, batch]",
        "    #   exporters: [otlphttp/remnant]",
        "",
    ]
    return "\n".join(out)
