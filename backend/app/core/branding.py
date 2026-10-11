"""Product branding.

The product name is a working codename. This constant is the only place it is
defined on the backend. The frontend reads it from GET /api/meta, so a rename
is a one-line change here. Do not use the product name in package or module
names.
"""

from typing import Final

PRODUCT_NAME: Final[str] = "Remnant"
