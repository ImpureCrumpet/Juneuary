"""Solar geometry helpers.

Pure stdlib. Accurate to ~0.5° for declination — plenty for microseason
classification. Used to flag Photon Fraud (sun is up but useless because
elevation is too low for vitamin D synthesis) and to gate Glorious Sun
(needs both bright sky AND a high-enough sun for it to actually feel warm).
"""

from __future__ import annotations

import math
from datetime import date


def day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def declination_deg(d: date) -> float:
    """Sun's declination in degrees. Cooper's formula."""
    n = day_of_year(d)
    return 23.45 * math.sin(math.radians(360.0 * (284 + n) / 365.0))


def max_solar_elevation_deg(latitude_deg: float, d: date) -> float:
    """Maximum solar elevation (at local solar noon) on a given date.

    For lat in the northern hemisphere this is `90 - |lat - declination|`.
    The same formula works for southern lats; the abs handles both sides.

    Examples (Seattle, 47.6°N):
        Dec solstice: ~19°  -> well into Photon Fraud territory
        Jun solstice: ~66°  -> bright enough for everything
    """
    decl = declination_deg(d)
    return 90.0 - abs(latitude_deg - decl)


# Thresholds we use elsewhere ------------------------------------------------

# UVB-meaningful threshold: below this, vitamin D synthesis is negligible
# even at peak local noon (atmospheric absorption dominates). This is the
# "Photon Fraud" line.
PHOTON_FRAUD_MAX_ELEVATION_DEG: float = 30.0

# "Glorious Sun"-eligible: sun is high enough to feel warm on skin even in
# cool air. Empirically ~35° gets you there in dry-ish PNW conditions.
GLORIOUS_SUN_MIN_ELEVATION_DEG: float = 35.0
