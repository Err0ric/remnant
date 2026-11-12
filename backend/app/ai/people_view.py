"""View people in AI usage (ADR-0029 G1 to G3, D242).

Who may see person names on AI surfaces, what they see instead, and the audit row each
response writes. Routes mask in their responses with these helpers; the UI never decides.
"""

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Any

from app.auth.users import User
from app.meta.audit import AuditLog

HIDDEN = "Hidden"

# Orders rows that tie on every shown value by a keyed hash of the name, never by the name
# itself, so a masked row's place says nothing about who it is (D242).
_TIE = secrets.token_bytes(16)


def tie(name: str) -> bytes:
    return hmac.new(_TIE, name.encode(), hashlib.sha256).digest()


def can_view_people(user: User) -> bool:
    """Admins always may (G1); anyone else only with the permission an admin granted."""
    return user.role == "admin" or user.view_ai_people


def mask_person(name: str | None, machine: str | None) -> str | None:
    """What a viewer without the permission sees for a person (G2): the machine or address
    when the row has one, else "Hidden". A row with no person stays without one, so counts
    and empty cells read the same for every viewer."""
    if name is None:
        return None
    return machine or HIDDEN


def audit_ai_view(
    audit: AuditLog,
    user: User,
    ip: str | None,
    surface: str,
    start: datetime | None,
    end: datetime | None,
    sources_in_scope: list[str] | None,
    named: bool,
    **extra: Any,
) -> None:
    """One audit row per AI response (G3): `ai.view_people` when it carried names,
    `ai.view` when it did not. `sources_in_scope` None is every source (an administrator).
    Blocking: call it through the thread pool."""
    detail: dict[str, Any] = {
        "surface": surface,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "sources_in_scope": sources_in_scope,
        **extra,
    }
    action = "ai.view_people" if named else "ai.view"
    audit.write(action, "success", user.user_id, ip, detail)
