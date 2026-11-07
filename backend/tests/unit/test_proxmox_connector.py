"""The Proxmox connector's parsing and checks (ADR-0045 A1, A3a, A7, A8), with no network."""

import ssl
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import ValidationError

from app.ingest.connectors.base import ConnectorError
from app.ingest.connectors.proxmox import (
    ProxmoxSettings,
    changes,
    check_permissions,
    check_secret,
    config_parts,
    reported_ips,
    tls_context,
)

SECRET = "FAKE-SECRET-d41d8cd98f00"


def test_config_keeps_only_macs_and_the_ip_part_of_ipconfig() -> None:
    config = {
        "net0": "virtio=52:54:00:12:34:56,bridge=vmbr0,tag=30",
        "net1": "name=eth1,hwaddr=52:54:00:AA:BB:01,ip=192.168.10.5/24,gw=192.168.10.1",
        "ipconfig0": "ip=10.20.30.40/24,gw=10.20.30.1,ip6=2001:db8::40/64",
        "ipconfig1": "ip=dhcp",
        "nameserver": "10.0.0.53",
        "searchdomain": "corp.internal",
        "cipassword": SECRET,
        "sshkeys": SECRET,
        "description": SECRET,
        "agent": "enabled=1,fstrim_cloned_disks=1",
    }
    macs, ips, agent = config_parts(config)
    assert macs == ["52:54:00:12:34:56", "52:54:00:aa:bb:01"]
    assert ips == ["192.168.10.5", "10.20.30.40"]
    assert agent is True
    assert SECRET not in repr((macs, ips, agent))
    assert config_parts({"agent": "0"})[2] is False


def test_reported_addresses_drop_loopback_and_link_local() -> None:
    agent = {"result": [
        {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1"}, {"ip-address": "::1"}]},
        {"name": "eth0", "ip-addresses": [{"ip-address": "10.0.0.5"}, {"ip-address": "fe80::1"}]},
    ]}  # fmt: skip
    assert reported_ips(agent) == ["10.0.0.5"]
    lxc = [{"name": "eth0", "inet": "192.168.10.5/24", "inet6": "2001:db8::5/64"}]
    assert reported_ips(lxc) == ["192.168.10.5", "2001:db8::5"]
    assert reported_ips("junk") == [] and reported_ips([{"inet": "not an ip"}]) == []


def test_changes_name_only_tracked_fields() -> None:
    a: dict[str, Any] = {"name": "a", "node": "pve1", "status": "running", "macs": [],
                         "ips": [{"ip": "10.0.0.5", "from": "agent"}], "tags": []}  # fmt: skip
    assert changes(a, {**a, "ips": [{"ip": "10.0.0.5", "from": "config"}]}) == []
    assert changes(a, {**a, "ips": [], "tags": ["x"]}) == ["ip", "tag"]


class Fake:
    def __init__(self, perms: Any) -> None:
        self.perms = perms

    def get(self, path: str) -> Any:
        return self.perms


def test_any_privilege_beyond_auditor_refuses_even_when_not_propagated() -> None:
    check_permissions(Fake({"/": {"Sys.Audit": 1, "VM.Audit": 1}}))  # type: ignore[arg-type]  # a duck-typed fake client
    for extra in ("Sys.Modify", "VM.Allocate", "VM.Monitor", "Something.New"):
        with pytest.raises(ConnectorError, match="PVEAuditor"):
            check_permissions(Fake({"/": {"VM.Audit": 1}, "/vms/104": {extra: 0}}))  # type: ignore[arg-type]  # a duck-typed fake client
    with pytest.raises(ConnectorError):
        check_permissions(Fake(None))  # type: ignore[arg-type]  # a duck-typed fake client


def _ca_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pve cluster CA")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_tls_is_always_verified_and_a_pinned_ca_is_the_only_trust() -> None:
    plain = ProxmoxSettings(host="pve1.example.internal", token_id="remnant@pve!inventory")
    assert tls_context(plain) is True
    pinned = ProxmoxSettings(
        host="pve1.example.internal", token_id="remnant@pve!inventory", ca_pem=_ca_pem()
    )
    ctx = tls_context(pinned)
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname and len(ctx.get_ca_certs()) == 1
    with pytest.raises(ValidationError, match="PEM"):
        ProxmoxSettings(host="pve1.example.internal", token_id="a@pve!b", ca_pem="nope")
    with pytest.raises(ValidationError):
        ProxmoxSettings.model_validate(
            {"host": "pve1.example.internal", "token_id": "a@pve!b", "verify": False}
        )


def test_settings_and_secret_shapes() -> None:
    with pytest.raises(ValidationError, match="user@realm!name"):
        ProxmoxSettings(host="pve1.example.internal", token_id="root@pam")
    with pytest.raises(ValidationError, match="host name only"):
        ProxmoxSettings(host="https://pve1.example.internal", token_id="a@pve!b")
    assert ProxmoxSettings(host="PVE1.example.internal", token_id="a@pve!b").host == (
        "pve1.example.internal"
    )
    with pytest.raises(ConnectorError):
        check_secret("not-a-uuid")
