"""Turning asset codes into Python attribute names.

Asset codes are not all valid Python identifiers. Roughly 4% of them contain
``~`` or ``-`` and another 4% start with a digit. ``alias_for`` maps a code to
the name used for attribute access and in generated stubs:

=================================================  =================================================
code                                               alias
=================================================  =================================================
``Lamborghini_AventadorLP7004_2011_loda``          ``Lamborghini_AventadorLP7004_2011_loda``
``Ford_GT40MkII_1966_Wheel_1_Calliper1_A_~_meshes``  ``Ford_GT40MkII_1966_Wheel_1_Calliper1_A_meshes``
``Localisation_PT-BR``                             ``Localisation_PT_BR``
``10A18Nb``                                        ``_10A18Nb``
=================================================  =================================================

The mapping is not injective in principle, so :class:`~csr2cdn.database.AssetCollection`
detects collisions rather than assuming there are none. On the 6_7_0_Release_OTA_1
database (23,496 assets) it produces no collisions at all, not even when compared
case-insensitively.
"""

from __future__ import annotations

import re

_INVALID = re.compile(r"[^0-9A-Za-z_]")


def alias_for(code: str) -> str:
    """Return the Python attribute name used for *code*."""
    alias = code.replace("_~_", "_").replace("~", "_").replace("-", "_")
    alias = _INVALID.sub("_", alias)
    if not alias:
        return "_"
    if alias[0].isdigit():
        alias = "_" + alias
    return alias
