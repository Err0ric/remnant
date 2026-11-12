"""Alert sources (ADR-0049 3.1): what a line from an `emits: alerts` template must carry to
raise an alert item, and the key it is deduplicated by.

The line itself is always stored (rule 5). A complete alert keeps its key in `unmapped`
under ALERT_KEY, which the alert watch reads; an incomplete one is stored `partial` with
`alert_missing:<fields>` and raises nothing.
"""

from typing import Any

from app.templates.transforms import MISSING, get_path
from app.templates.validator import AlertSpec

ALERT_KEY = "_alert"
MAX_KEY = 200
# Who or what the alert is about. The reporting device's name counts only when the template
# maps it: a syslog header's host is the sensor that sent the alert, not its subject.
_ENTITIES = ("src_endpoint_ip", "src_endpoint_hostname", "actor_user_name")
_NO_VALUE: tuple[Any, ...] = (MISSING, None, "", "-")


def _text(value: Any) -> str | None:
    if value in _NO_VALUE:
        return None
    text = str(value).strip()[:MAX_KEY]
    return text or None


def alert_key(
    spec: AlertSpec, fields: dict[str, Any], row: dict[str, Any], maps_device: bool = False
) -> tuple[dict[str, str], list[str]]:
    """({"id", "product"}, missing required fields) for one parsed line."""
    uid = next((t for r in spec.ids if (t := _text(get_path(fields, r)))), None)
    product = " ".join(t for r in spec.products if (t := _text(get_path(fields, r))))
    missing = []
    if uid is None:
        missing.append("id")
    if not product:
        missing.append("product")
    if row.get("time") is None:
        missing.append("time")
    if _text(row.get("message")) is None:
        missing.append("title")
    if row.get("severity_id") not in (1, 2, 3, 4, 5, 6):
        missing.append("severity")
    entities = (*_ENTITIES, "device_hostname") if maps_device else _ENTITIES
    if not any(_text(row.get(c)) for c in entities):
        missing.append("entity")
    return {"id": uid or "", "product": product[:MAX_KEY]}, missing
