"""A fake Proxmox VE API (ADR-0045) for tests: no network, shapes of Proxmox 8 and 9.

On 8 the guest agent's interface list needs VM.Monitor, which a PVEAuditor token lacks, so
it answers 403; on 9 it needs VM.GuestAgent.Audit, which PVEAuditor has. Guest configs carry
a description, notes, and cloud-init fields holding SECRET, which must never be stored.
"""

from __future__ import annotations

import copy
import json
from typing import Any
from urllib.parse import unquote

import httpx

TOKEN_ID = "remnant@pve!inventory"
TOKEN_SECRET = "0b5e7c1a-3f2d-4e8a-9c6b-1d2e3f4a5b6c"
SECRET = "FAKE-SECRET-d41d8cd98f00"
AUDITOR_8 = ["Datastore.Audit", "Mapping.Audit", "Pool.Audit", "SDN.Audit", "Sys.Audit", "VM.Audit"]


def _secret_fields() -> dict[str, str]:
    return {
        "description": f"build box, root password {SECRET}",
        "notes": f"vault token {SECRET}",
        "cipassword": f"$5${SECRET}",
        "ciuser": "admin",
        "sshkeys": f"ssh-ed25519%20AAAA{SECRET}%20admin%40example.com",
        "nameserver": "10.0.0.53",
        "searchdomain": "corp.internal",
    }


def default_guests() -> dict[int, dict[str, Any]]:
    """VMID -> resource, config, and what the guest reports (None: agent not running)."""
    return {
        104: {
            "res": {"vmid": 104, "type": "qemu", "name": "build-runner", "node": "pve2",
                    "status": "running", "tags": "ci;linux"},
            "config": {"net0": "virtio=52:54:00:12:34:56,bridge=vmbr0,tag=30",
                       "ipconfig0": "ip=10.20.30.40/24,gw=10.20.30.1", "agent": "1",
                       **_secret_fields()},
            "report": [{"name": "lo", "hardware-address": "00:00:00:00:00:00",
                        "ip-addresses": [{"ip-address": "127.0.0.1", "prefix": 8}]},
                       {"name": "eth0", "hardware-address": "52:54:00:12:34:56",
                        "ip-addresses": [{"ip-address": "10.20.30.41", "prefix": 24},
                                         {"ip-address": "fe80::5054:ff:fe12:3456", "prefix": 64}]}],
        },
        105: {  # no guest agent, DHCP: MAC only
            "res": {"vmid": 105, "type": "qemu", "name": "scanner", "node": "pve1",
                    "status": "running"},
            "config": {"net0": "e1000=52:54:00:ab:cd:05,bridge=vmbr1",
                       "ipconfig0": "ip=dhcp", **_secret_fields()},
            "report": None,
        },
        201: {
            "res": {"vmid": 201, "type": "lxc", "name": "dns-cache", "node": "pve1",
                    "status": "running", "tags": "dns"},
            "config": {"net0": "name=eth0,bridge=vmbr0,hwaddr=52:54:00:AA:BB:01,ip=192.168.10.5/24,"
                               "gw=192.168.10.1,type=veth",
                       "description": f"notes {SECRET}"},
            "report": [{"name": "lo", "hwaddr": "00:00:00:00:00:00", "inet": "127.0.0.1/8"},
                       {"name": "eth0", "hwaddr": "52:54:00:aa:bb:01", "inet": "192.168.10.5/24",
                        "inet6": "2001:db8::5/64"}],
        },
        900: {  # a template: never listed as a guest
            "res": {"vmid": 900, "type": "qemu", "name": "tmpl-debian", "node": "pve1",
                    "status": "stopped", "template": 1},
            "config": {"net0": "virtio=52:54:00:00:09:00,bridge=vmbr0"},
            "report": None,
        },
    }  # fmt: skip


class FakeProxmox:
    def __init__(self, version: int = 9) -> None:
        self.version = version
        self.guests = default_guests()
        self.privs: dict[str, dict[str, int]] = {"/": dict.fromkeys(self.auditor(), 1)}
        self.calls: list[str] = []

    def auditor(self) -> list[str]:
        return AUDITOR_8 + (["VM.GuestAgent.Audit"] if self.version >= 9 else [])

    def grant(self, *privs: str) -> None:
        self.privs.setdefault("/vms", {}).update(dict.fromkeys(privs, 0))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _ok(self, data: Any) -> httpx.Response:
        return httpx.Response(200, json={"data": data})

    def _handle(self, req: httpx.Request) -> httpx.Response:
        if req.headers.get("authorization") != f"PVEAPIToken={TOKEN_ID}={TOKEN_SECRET}":
            return httpx.Response(401, json={"data": None})
        path = unquote(req.url.path).removeprefix("/api2/json")
        self.calls.append(path)
        if path == "/version":
            return self._ok({"version": f"{self.version}.0.3", "release": f"{self.version}.0"})
        if path == "/access/permissions":
            return self._ok(copy.deepcopy(self.privs))
        if path == "/cluster/resources":
            return self._ok([g["res"] for g in self.guests.values()])
        parts = path.strip("/").split("/")  # nodes/<node>/<type>/<vmid>/...
        if len(parts) < 5 or parts[0] != "nodes":
            return httpx.Response(404, json={"data": None})
        guest = self.guests.get(int(parts[3]))
        if guest is None or guest["res"]["type"] != parts[2]:
            return httpx.Response(500, json={"data": None})
        rest = "/".join(parts[4:])
        if rest == "config":
            return self._ok(copy.deepcopy(guest["config"]))
        if rest == "interfaces" and parts[2] == "lxc":
            return self._ok(copy.deepcopy(guest["report"] or []))
        if rest == "agent/network-get-interfaces" and parts[2] == "qemu":
            if self.version < 9:
                return httpx.Response(403, json={"data": None})
            if guest["report"] is None:
                return httpx.Response(500, content=json.dumps({"data": None}).encode())
            return self._ok({"result": copy.deepcopy(guest["report"])})
        return httpx.Response(501, json={"data": None})
