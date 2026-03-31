from __future__ import annotations

import math


def sat_vapor_pressure_kpa(temp_c: float) -> float:
    """
    Saturation vapor pressure (kPa) using the Tetens formula.
    Good accuracy for typical grow-tent temperature ranges.
    """
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def vpd_kpa(temp_c: float, rh_percent: float) -> float:
    """
    Ambient VPD approximation (kPa):
      VPD = SVP(air) * (1 - RH/100)
    """
    rh = max(0.0, min(100.0, float(rh_percent)))
    es = sat_vapor_pressure_kpa(float(temp_c))
    return max(0.0, es * (1.0 - rh / 100.0))


def vpd_leaf_kpa(air_temp_c: float, rh_percent: float, leaf_temp_c: float) -> float:
    """
    Leaf VPD (kPa):
      VPD_leaf = SVP(leaf) - AVP(air)
      AVP(air) = RH% * SVP(air)
    """
    rh = max(0.0, min(100.0, float(rh_percent)))
    avp = (rh / 100.0) * sat_vapor_pressure_kpa(float(air_temp_c))
    vpd = sat_vapor_pressure_kpa(float(leaf_temp_c)) - avp
    return max(0.0, vpd)


def dew_point_c(temp_c: float, rh_percent: float) -> float:
    """
    Dew point (°C) using the Magnus formula.
    """
    a = 17.625
    b = 243.04
    rh = max(0.1, min(100.0, float(rh_percent)))
    t = float(temp_c)
    alpha = math.log(rh / 100.0) + (a * t) / (b + t)
    return (b * alpha) / (a - alpha)


def safe_float(x) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except (ValueError, TypeError):
        return None


def avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)
