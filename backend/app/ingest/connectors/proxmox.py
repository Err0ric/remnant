"""Proxmox VE guest inventory (ADR-0045 Part A, D210).

One API token per cluster or host, with the PVEAuditor role only: `GET /access/permissions`
is checked when the source is saved and on every poll, and a token with any privilege
outside PVEAuditor's set is refused. TLS is always verified, against the system store or a
pinned cluster CA; there is no way to skip it.

Each poll reads `/cluster/resources?type=vm`, then per guest its config, and for running
guests the addresses they report (`lxc/{vmid}/interfaces`, or for VMs with the guest agent
`qemu/{vmid}/agent/network-get-interfaces`). Responses are read in memory and a record is
built from an allowlist (A3a): name, VMID, type, node, status, tags, MACs, IPs and where
each IP came from. Descriptions, notes, and every cloud-init field other than the address
in `ipconfigN`'s `ip=` are never kept, so they never reach the lake, a log line, or a
model. Records are written only when a guest appears, changes, or disappears, plus one
heartbeat per guest a day (A3b).

Errors and warnings name no guest, node, or address.
"""

from __future__ import annotations

import ipaddress
import json
import re
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from cryptography import x509
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.alerts.net import check_url, egress
from app.core.errors import ParamInvalidError
from app.ingest.connectors.base import TIMEOUT, ConnectorError, Pull, Record

POLL_EVERY = timedelta(minutes=15)
HEARTBEAT = timedelta(days=1)
MAX_BODY = 8 * 1024 * 1024
MAX_GUESTS = 5000
# PVEAuditor's privileges on Proxmox VE 8 and 9 (9 adds VM.GuestAgent.Audit). Anything
# else, including privileges this list does not know, refuses the token (A7).
AUDITOR_PRIVS = frozenset(
    {
        "Datastore.Audit",
        "Mapping.Audit",
        "Pool.Audit",
        "SDN.Audit",
        "Sys.Audit",
        "VM.Audit",
        "VM.GuestAgent.Audit",
    }
)
AGENT_DENIED = "Agent IPs not available with this token"
CONTAINER_DENIED = "Container IPs not available with this token"
VERIFIED = "Verified on Proxmox 8 and 9: pending"

_TOKEN_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}![A-Za-z][A-Za-z0-9._-]{0,63}$")
_SECRET = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$|^\[?[0-9A-Fa-f:.]{2,45}\]?$")
_MAC = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
_NET = re.compile(r"^net\d{1,2}$")
_IPCONFIG = re.compile(r"^ipconfig\d{1,2}$")


class ProxmoxSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=253)  # a node or cluster name, no scheme
    port: int = Field(default=8006, ge=1, le=65535)
    token_id: str = Field(min_length=5, max_length=170)  # user@realm!name
    ca_pem: str | None = Field(default=None, max_length=32768)  # pinned cluster CA
    poll_minutes: int = Field(default=15, ge=5, le=1440)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        value = value.strip().lower()
        if not _HOST.fullmatch(value):
            raise ValueError("Give the host name only, for example pve1.example.internal")
        return value.strip("[]")

    @field_validator("token_id")
    @classmethod
    def _token_id(cls, value: str) -> str:
        value = value.strip()
        if not _TOKEN_ID.fullmatch(value):
            raise ValueError(
                "Token ID looks like user@realm!name, for example remnant@pve!inventory"
            )
        return value

    @field_validator("ca_pem")
    @classmethod
    def _ca(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            certs = x509.load_pem_x509_certificates(value.strip().encode())
        except ValueError:
            raise ValueError("The CA must be a PEM certificate") from None
        if not certs:
            raise ValueError("The CA must be a PEM certificate")
        return value.strip()

    @property
    def token_user(self) -> str:
        return self.token_id.split("!", 1)[0]


def check_secret(secret: str | None) -> str:
    if not secret or not _SECRET.fullmatch(secret.strip()):
        raise ConnectorError("Paste the token secret Proxmox showed when the token was made")
    return secret.strip()


class DeniedError(ConnectorError):
    """HTTP 403: the token lacks a privilege for this request."""


def tls_context(settings: ProxmoxSettings) -> ssl.SSLContext | bool:
    """Verify against the pinned CA only, or the system store (and network.ca_bundle)."""
    if settings.ca_pem:
        return ssl.create_default_context(cadata=settings.ca_pem)
    return egress().verify()


class ProxmoxClient:
    def __init__(
        self,
        settings: ProxmoxSettings,
        secret: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._s = settings
        self._auth = f"PVEAPIToken={settings.token_id}={check_secret(secret)}"
        self._transport = transport

    def get(self, path: str) -> Any:
        host = f"[{self._s.host}]" if ":" in self._s.host else self._s.host
        url = f"https://{host}:{self._s.port}/api2/json{path}"
        try:
            dest = check_url("webhook", url)  # resolves once; refuses metadata, link-local
        except ParamInvalidError as exc:
            raise ConnectorError(str(exc)) from None
        literal = f"[{dest.pin}]" if ":" in dest.pin else dest.pin
        target = urlunsplit(urlsplit(url)._replace(netloc=f"{literal}:{dest.port}"))
        headers = {"Host": f"{host}:{dest.port}", "Accept": "application/json"}
        headers["Authorization"] = self._auth
        try:
            with (
                httpx.Client(
                    timeout=TIMEOUT,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                    verify=tls_context(self._s),
                ) as client,
                client.stream(
                    "GET", target, headers=headers, extensions={"sni_hostname": dest.host}
                ) as res,
            ):
                data = b""
                for chunk in res.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BODY:
                        raise ConnectorError("Proxmox sent more than 8 MB in one reply")
                status = res.status_code
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Cannot reach Proxmox ({type(exc).__name__})") from None
        if status == 401:
            raise ConnectorError("Proxmox refused the token (HTTP 401)")
        if status == 403:
            raise DeniedError("Proxmox refused a request for lack of a privilege (HTTP 403)")
        if status != 200:
            raise ConnectorError(f"Proxmox answered HTTP {status}")
        try:
            return json.loads(data).get("data")
        except (ValueError, AttributeError):
            raise ConnectorError("Proxmox did not answer with JSON") from None


def check_permissions(client: ProxmoxClient) -> None:
    """Refuse a token that holds any privilege beyond PVEAuditor's (A7). A privilege
    listed with 0 is still granted (0 means it does not propagate), so it counts."""
    data = client.get("/access/permissions")
    if not isinstance(data, dict):
        raise ConnectorError("Proxmox did not list the token's permissions")
    extra: set[str] = set()
    for privs in data.values():
        if isinstance(privs, dict):
            extra |= {str(p) for p in privs} - AUDITOR_PRIVS
    if extra:
        names = ", ".join(sorted(extra)[:6]) + (" and more" if len(extra) > 6 else "")
        raise ConnectorError(
            f"This token can do more than read ({names}). Use a token with the PVEAuditor"
            " role only (docs/install/proxmox.md)"
        )


# --- the minimal record (A3a) ---------------------------------------------------------


def _kv(value: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(value, str):
        for part in value.split(","):
            k, sep, v = part.partition("=")
            if sep:
                out[k.strip()] = v.strip()
    return out


def _address(text: Any) -> str | None:
    """Only the address of `10.0.0.5/24`; loopback, link-local, and junk are dropped."""
    if not isinstance(text, str) or not text or len(text) > 64:
        return None
    try:
        ip = ipaddress.ip_interface(text.strip()).ip
    except ValueError:
        return None
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return None
    return str(ip)


def _mac(text: Any) -> str | None:
    return text.lower() if isinstance(text, str) and _MAC.fullmatch(text) else None


def config_parts(config: Any) -> tuple[list[str], list[str], bool]:
    """MACs, static addresses, and whether the guest agent is on, from a guest config.

    Reads `netN` (MAC values, and LXC's `ip=`), `ipconfigN` (`ip=` only), and `agent`. No
    other key is read, and nothing is returned but MACs, addresses, and one flag."""
    macs: list[str] = []
    ips: list[str] = []
    agent = False
    if not isinstance(config, dict):
        return macs, ips, agent
    for key, value in config.items():
        if _NET.fullmatch(str(key)):
            parts = _kv(value)
            macs += [m for m in (_mac(v) for v in parts.values()) if m]
            ip = _address(parts.get("ip"))
            if ip:
                ips.append(ip)
        elif _IPCONFIG.fullmatch(str(key)):
            ip = _address(_kv(value).get("ip"))
            if ip:
                ips.append(ip)
        elif key == "agent":
            text = str(value)
            agent = text.startswith("1") or "enabled=1" in text
    return macs, ips, agent


def reported_ips(data: Any) -> list[str]:
    """Addresses from an LXC interfaces list or a guest agent reply."""
    items = data.get("result") if isinstance(data, dict) else data
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        for key in ("inet", "inet6"):
            ip = _address(item.get(key))
            if ip:
                out.append(ip)
        for entry in item.get("ip-addresses") or []:
            if isinstance(entry, dict):
                ip = _address(entry.get("ip-address"))
                if ip:
                    out.append(ip)
    return out


def _tags(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return sorted({t[:64] for t in re.split(r"[;,\s]+", value) if t})[:20]


def _text(value: Any, cap: int = 128) -> str:
    return str(value)[:cap] if value is not None else ""


def guest_record(
    resource: dict[str, Any], macs: list[str], ips: list[tuple[str, str]]
) -> dict[str, Any]:
    seen: dict[str, str] = {}
    for ip, origin in ips:
        seen.setdefault(ip, origin)
    return {
        "vmid": int(resource["vmid"]),
        "type": resource["type"],
        "name": _text(resource.get("name")),
        "node": _text(resource.get("node"), 64),
        "status": _text(resource.get("status"), 32),
        "tags": _tags(resource.get("tags")),
        "macs": sorted(set(macs))[:32],
        "ips": [{"ip": ip, "from": o} for ip, o in sorted(seen.items())][:64],
    }


TRACKED = ("name", "node", "status", "macs", "ips", "tags")


def changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    def ipset(rec: dict[str, Any]) -> list[str]:
        return sorted(str(x.get("ip")) for x in rec.get("ips") or [])

    out = []
    for key in TRACKED:
        a, b = (ipset(before), ipset(after)) if key == "ips" else (before.get(key), after.get(key))
        if a != b:
            out.append(
                "ip" if key == "ips" else key.rstrip("s") if key in ("macs", "tags") else key
            )
    return out


def event_line(event: str, rec: dict[str, Any], now: datetime, changed: list[str]) -> str:
    body: dict[str, Any] = {
        "feed": "proxmox.guest",
        "event": event,
        "time": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        **rec,
    }
    if changed:
        body["changed"] = changed
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


# --- the connector ----------------------------------------------------------------------


def _path(*parts: str | int) -> str:
    return "/" + "/".join(quote(str(p), safe="") for p in parts)


def list_guests(client: ProxmoxClient) -> list[dict[str, Any]]:
    """VMs and containers, templates left out (they never run, so they hold no address)."""
    data = client.get("/cluster/resources?type=vm")
    if not isinstance(data, list):
        raise ConnectorError("Proxmox did not list its guests")
    out = []
    for r in data[:MAX_GUESTS]:
        if not isinstance(r, dict) or r.get("type") not in ("qemu", "lxc") or r.get("template"):
            continue
        if isinstance(r.get("vmid"), int) and isinstance(r.get("node"), str):
            out.append(r)
    return out


class ProxmoxConnector:
    def __init__(self, settings: ProxmoxSettings, client: ProxmoxClient) -> None:
        self._c = client
        self.poll_every = timedelta(minutes=settings.poll_minutes)

    def pull(self, checkpoint: str | None, now: datetime) -> Pull:
        try:
            cp = json.loads(checkpoint) if checkpoint else {}
            prev: dict[str, Any] = dict(cp.get("guests") or {})
        except (ValueError, AttributeError):
            prev = {}
        check_permissions(self._c)
        state = {"agent_denied": False, "lxc_denied": False, "failed": 0}
        current: dict[str, Any] = {}
        records: list[Record] = []
        for r in list_guests(self._c):
            key = str(r["vmid"])
            before = prev.get(key)
            try:
                rec = self._record(r, before["rec"] if before else None, state)
            except ConnectorError:
                state["failed"] += 1
                if before:
                    current[key] = before  # unread this poll: kept as it was
                continue
            if before is None:
                event, changed = "appeared", []
            else:
                changed = changes(before["rec"], rec)
                last = datetime.fromisoformat(str(before.get("at")))
                event = "changed" if changed else "heartbeat" if now - last >= HEARTBEAT else ""
            if event:
                records.append(Record(event_line(event, rec, now, changed), now))
                current[key] = {"rec": rec, "at": now.isoformat()}
            else:
                current[key] = before
        for key, gone in prev.items():
            if key not in current:
                records.append(Record(event_line("disappeared", gone["rec"], now, []), now))
        warnings = []
        if state["agent_denied"]:
            warnings.append(AGENT_DENIED)
        if state["lxc_denied"]:
            warnings.append(CONTAINER_DENIED)
        if state["failed"]:
            warnings.append(f"Could not read {state['failed']} guest configs this poll")
        return Pull(records, json.dumps({"guests": current}), None, warnings)

    def _record(
        self, r: dict[str, Any], before: dict[str, Any] | None, state: dict[str, Any]
    ) -> dict[str, Any]:
        node, vmid, kind = r["node"], r["vmid"], r["type"]
        config = self._c.get(_path("nodes", node, kind, vmid, "config"))
        macs, static, agent = config_parts(config)
        del config  # nothing else of it is kept
        ips: list[tuple[str, str]] = [(ip, "config") for ip in static]
        old = [x["ip"] for x in (before or {}).get("ips") or [] if x.get("from") != "config"]
        if r.get("status") == "running":
            if kind == "lxc" and not state["lxc_denied"]:
                ips += [(ip, "container") for ip in self._reported(kind, node, vmid, old, state)]
            elif kind == "qemu" and agent and not state["agent_denied"]:
                ips += [(ip, "agent") for ip in self._reported(kind, node, vmid, old, state)]
        return guest_record(r, macs, ips)

    def _reported(
        self, kind: str, node: str, vmid: int, old: list[str], state: dict[str, Any]
    ) -> list[str]:
        path = (
            _path("nodes", node, "lxc", vmid, "interfaces")
            if kind == "lxc"
            else _path("nodes", node, "qemu", vmid, "agent", "network-get-interfaces")
        )
        try:
            return reported_ips(self._c.get(path))
        except DeniedError:
            # Never ask for more privileges: record config addresses only (owner 2026-11-06).
            state["agent_denied" if kind == "qemu" else "lxc_denied"] = True
            return []
        except ConnectorError:
            return old  # agent not answering this time: keep what it reported before


def test_connection(client: ProxmoxClient) -> dict[str, str]:
    """The permission check, the version, and a guest count, before the source is saved."""
    out: dict[str, str] = {}
    try:
        check_permissions(client)
        out["permissions"] = "ok: read only (PVEAuditor)"
    except ConnectorError as exc:
        return {"permissions": str(exc)}
    try:
        version = client.get("/version")
        release = version.get("version") if isinstance(version, dict) else None
        out["version"] = f"ok: Proxmox VE {_text(release, 32)}" if release else "ok"
    except ConnectorError as exc:
        out["version"] = str(exc)
    try:
        out["guests"] = f"ok: {len(list_guests(client))} guests"
    except ConnectorError as exc:
        out["guests"] = str(exc)
    return out
