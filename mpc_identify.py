#!/usr/bin/env python3
"""
MPC Model Identification Script — Small Grow Tent Controller
=============================================================

Reads raw state history from your Home Assistant SQLite database and fits
a simple first-order thermal/humidity model for use with Model Predictive
Control.

The model:
    temp(t+1) = temp(t) + a_heater*H(t) + a_exhaust*E(t) + a_passive*(temp_amb - temp(t)) + a_bias
    rh(t+1)   = rh(t)   + b_exhaust*E(t) + b_passive*(rh_amb  - rh(t))   + b_bias

Where:
    H(t)         = 1 if heater is on, 0 if off
    E(t)         = 1 if exhaust is on, 0 if off
    temp_amb     = ambient temperature proxy (estimated as min tent temp during exhaust-on periods)
    rh_amb       = ambient RH proxy (estimated as min tent RH during exhaust-on periods)
    a_*, b_*     = model parameters to be identified

Usage
-----
1. Copy this script to your HA machine (or a machine with access to the DB).
2. Edit the CONFIGURATION section below.
3. Run:  python3 mpc_identify.py
4. Paste the printed parameters into your grow tent controller config.

Requirements: numpy, scipy, pandas, matplotlib
    pip install numpy scipy pandas matplotlib
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')   # non-interactive backend — saves plots to files
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# =============================================================================
# CONFIGURATION — edit these to match your setup
# =============================================================================

# Path to your HA SQLite database
# On most HA installations this is at /config/home-assistant_v2.db
# If running this on a different machine, copy the DB file locally first.
HA_DB_PATH = "/config/home-assistant_v2.db"

# Entity IDs — update to match your exact entity IDs in HA
ENTITY_CANOPY_TEMP   = "sensor.sht41_1_temperature"
ENTITY_TOP_TEMP      = "sensor.sht41_2_temperature"
ENTITY_CANOPY_RH     = "sensor.sht41_1_humidity"
ENTITY_TOP_RH        = "sensor.sht41_2_humidity"
ENTITY_HEATER        = "switch.heatergrowtent"
ENTITY_EXHAUST       = "switch.exhaustgrowtent"

# How many days of history to use for fitting
HISTORY_DAYS = 7

# Resample interval — must match controller poll rate (10 seconds)
RESAMPLE_S = 10

# Output directory for plots
OUTPUT_DIR = "."

# Percentile used to estimate ambient conditions from exhaust-on periods
# Lower = more conservative (cooler/drier ambient estimate)
AMBIENT_PERCENTILE = 10

# =============================================================================
# END CONFIGURATION
# =============================================================================


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_entity_history(conn: sqlite3.Connection, entity_id: str, since: datetime) -> pd.Series:
    """Load raw state history for one entity from the HA recorder database."""

    # HA stores entity metadata in states_meta (newer versions) or inline
    # Try states_meta first, fall back to the old schema
    since_ts = since.timestamp()

    try:
        cur = conn.execute(
            """
            SELECT s.last_updated_ts, s.state
            FROM states s
            JOIN states_meta m ON s.metadata_id = m.metadata_id
            WHERE m.entity_id = ?
              AND s.last_updated_ts >= ?
              AND s.state NOT IN ('unavailable', 'unknown', '')
            ORDER BY s.last_updated_ts
            """,
            (entity_id, since_ts),
        )
    except sqlite3.OperationalError:
        # Older HA schema without states_meta
        cur = conn.execute(
            """
            SELECT last_updated_ts, state
            FROM states
            WHERE entity_id = ?
              AND last_updated_ts >= ?
              AND state NOT IN ('unavailable', 'unknown', '')
            ORDER BY last_updated_ts
            """,
            (entity_id, since_ts),
        )

    rows = cur.fetchall()
    if not rows:
        raise ValueError(f"No history found for entity '{entity_id}'. "
                         f"Check the entity ID in the CONFIGURATION section.")

    timestamps = [datetime.fromtimestamp(r[0], tz=timezone.utc) for r in rows]
    values     = [r[1] for r in rows]

    series = pd.Series(values, index=pd.DatetimeIndex(timestamps), name=entity_id)
    log(f"  Loaded {len(series):,} rows for {entity_id}")
    return series


def parse_numeric(series: pd.Series) -> pd.Series:
    """Convert string states to float, dropping non-numeric."""
    return pd.to_numeric(series, errors="coerce").dropna()


def parse_switch(series: pd.Series) -> pd.Series:
    """Convert on/off states to 1/0."""
    return series.map({"on": 1.0, "off": 0.0}).dropna()


def resample_forward_fill(series: pd.Series, freq: str) -> pd.Series:
    """Resample to fixed frequency using forward-fill (step function for switches)."""
    return series.resample(freq).last().ffill()


def build_dataset(
    canopy_temp: pd.Series,
    top_temp: pd.Series,
    canopy_rh: pd.Series,
    top_rh: pd.Series,
    heater: pd.Series,
    exhaust: pd.Series,
    resample_s: int,
) -> pd.DataFrame:
    """Resample all series to common grid and compute average temp/RH."""
    freq = f"{resample_s}s"

    ct = resample_forward_fill(parse_numeric(canopy_temp), freq)
    tt = resample_forward_fill(parse_numeric(top_temp),    freq)
    cr = resample_forward_fill(parse_numeric(canopy_rh),   freq)
    tr = resample_forward_fill(parse_numeric(top_rh),      freq)
    h  = resample_forward_fill(parse_switch(heater),       freq)
    e  = resample_forward_fill(parse_switch(exhaust),      freq)

    df = pd.DataFrame({
        "canopy_temp": ct,
        "top_temp":    tt,
        "canopy_rh":   cr,
        "top_rh":      tr,
        "heater":      h,
        "exhaust":     e,
    }).dropna()

    df["avg_temp"] = (df["canopy_temp"] + df["top_temp"]) / 2.0
    df["avg_rh"]   = (df["canopy_rh"]  + df["top_rh"])   / 2.0

    return df


def estimate_ambient(df: pd.DataFrame, percentile: int) -> tuple[float, float]:
    """
    Estimate ambient (lung room) temperature and RH.

    When the exhaust is on, tent conditions are being pulled toward ambient.
    The low-percentile values during exhaust-on periods give a conservative
    estimate of ambient conditions.
    """
    exhaust_on = df[df["exhaust"] == 1]
    if len(exhaust_on) < 10:
        log("  WARNING: very few exhaust-on samples — ambient estimate may be poor.")
        log("  Using overall minimum as fallback.")
        return df["avg_temp"].quantile(percentile / 100), df["avg_rh"].quantile(percentile / 100)

    temp_amb = exhaust_on["avg_temp"].quantile(percentile / 100)
    rh_amb   = exhaust_on["avg_rh"].quantile(percentile / 100)
    return temp_amb, rh_amb


def fit_temperature_model(df: pd.DataFrame, temp_amb: float) -> dict:
    """
    Fit first-order temperature model using OLS regression.

    Model: delta_temp = a_heater*H + a_exhaust*E + a_passive*(temp_amb - temp) + a_bias

    delta_temp = temp(t+1) - temp(t)  [°C per poll interval]
    """
    # Compute temperature delta (one step ahead)
    delta_temp = df["avg_temp"].diff().shift(-1).dropna()
    aligned    = df.loc[delta_temp.index]

    X = pd.DataFrame({
        "heater":  aligned["heater"],
        "exhaust": aligned["exhaust"],
        "passive": temp_amb - aligned["avg_temp"],
        "bias":    1.0,
    })
    y = delta_temp

    # OLS regression
    result = np.linalg.lstsq(X.values, y.values, rcond=None)
    coeffs = result[0]

    # Compute R² for quality assessment
    y_pred  = X.values @ coeffs
    ss_res  = np.sum((y.values - y_pred) ** 2)
    ss_tot  = np.sum((y.values - y.values.mean()) ** 2)
    r2      = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    params = {
        "a_heater":  float(coeffs[0]),
        "a_exhaust": float(coeffs[1]),
        "a_passive": float(coeffs[2]),
        "a_bias":    float(coeffs[3]),
        "r2":        float(r2),
        "temp_amb":  float(temp_amb),
    }

    return params, X, y, y_pred


def fit_humidity_model(df: pd.DataFrame, rh_amb: float) -> dict:
    """
    Fit first-order humidity model using OLS regression.

    Model: delta_rh = b_exhaust*E + b_passive*(rh_amb - rh) + b_bias

    delta_rh = rh(t+1) - rh(t)  [% per poll interval]
    """
    delta_rh = df["avg_rh"].diff().shift(-1).dropna()
    aligned  = df.loc[delta_rh.index]

    X = pd.DataFrame({
        "exhaust": aligned["exhaust"],
        "passive": rh_amb - aligned["avg_rh"],
        "bias":    1.0,
    })
    y = delta_rh

    result = np.linalg.lstsq(X.values, y.values, rcond=None)
    coeffs = result[0]

    y_pred  = X.values @ coeffs
    ss_res  = np.sum((y.values - y_pred) ** 2)
    ss_tot  = np.sum((y.values - y.values.mean()) ** 2)
    r2      = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    params = {
        "b_exhaust": float(coeffs[0]),
        "b_passive": float(coeffs[1]),
        "b_bias":    float(coeffs[2]),
        "r2":        float(r2),
        "rh_amb":    float(rh_amb),
    }

    return params, X, y, y_pred


def simulate_model(df: pd.DataFrame, temp_params: dict, rh_params: dict) -> pd.DataFrame:
    """
    Run a full open-loop simulation using the fitted model.
    Start from the first real value and simulate forward using only
    the heater/exhaust inputs. This is the true test of model quality.
    """
    n = len(df)
    temp_sim = np.zeros(n)
    rh_sim   = np.zeros(n)
    temp_sim[0] = df["avg_temp"].iloc[0]
    rh_sim[0]   = df["avg_rh"].iloc[0]

    ta = temp_params["temp_amb"]
    ra = rh_params["rh_amb"]

    for i in range(n - 1):
        h = df["heater"].iloc[i]
        e = df["exhaust"].iloc[i]

        d_temp = (temp_params["a_heater"]  * h
                + temp_params["a_exhaust"] * e
                + temp_params["a_passive"] * (ta - temp_sim[i])
                + temp_params["a_bias"])
        d_rh   = (rh_params["b_exhaust"] * e
                + rh_params["b_passive"] * (ra - rh_sim[i])
                + rh_params["b_bias"])

        temp_sim[i + 1] = temp_sim[i] + d_temp
        rh_sim[i + 1]   = rh_sim[i]   + d_rh

    result = df.copy()
    result["temp_sim"] = temp_sim
    result["rh_sim"]   = rh_sim
    return result


def make_sanity_checks(temp_params: dict, rh_params: dict, resample_s: int) -> list[str]:
    """Check model parameters make physical sense."""
    warnings = []
    interval_min = resample_s / 60.0

    # Temperature rates in °C/min
    heater_rate  = temp_params["a_heater"]  / interval_min
    exhaust_rate = temp_params["a_exhaust"] / interval_min
    passive_rate = temp_params["a_passive"]

    if heater_rate <= 0:
        warnings.append(f"WARNING: heater rate is negative ({heater_rate:.3f}°C/min) — "
                        "heater appears to be cooling the tent. Check entity ID.")
    elif heater_rate > 3.0:
        warnings.append(f"WARNING: heater rate very high ({heater_rate:.3f}°C/min) — "
                        "may indicate data quality issues.")

    if exhaust_rate >= 0:
        warnings.append(f"WARNING: exhaust temp rate is positive ({exhaust_rate:.3f}°C/min) — "
                        "exhaust appears to be heating. Possible if lung room is warmer than tent.")

    if passive_rate < 0:
        warnings.append(f"WARNING: passive temp coefficient is negative ({passive_rate:.4f}) — "
                        "tent appears to self-heat passively. Check ambient estimate.")

    # RH rates in %/min
    exhaust_rh_rate = rh_params["b_exhaust"] / interval_min
    if exhaust_rh_rate >= 0:
        warnings.append(f"WARNING: exhaust RH rate is positive ({exhaust_rh_rate:.3f}%/min) — "
                        "exhaust appears to be humidifying. Check entity ID or ambient RH.")

    return warnings


def plot_results(df_sim: pd.DataFrame, temp_params: dict, rh_params: dict,
                 output_dir: str) -> None:
    """Generate validation plots."""

    # Use last 24h for detailed plots to keep them readable
    cutoff = df_sim.index[-1] - pd.Timedelta(hours=24)
    sample = df_sim[df_sim.index >= cutoff].copy()

    # Downsample to 1-minute for plotting
    sample_1m = sample.resample("1min").mean()

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    fig.suptitle("MPC Model Identification — Validation (last 24h)", fontsize=13, y=0.98)

    # Temperature
    ax = axes[0]
    ax.plot(sample_1m.index, sample_1m["avg_temp"], "b-",  lw=1.5, label="Actual avg temp", alpha=0.8)
    ax.plot(sample_1m.index, sample_1m["temp_sim"], "r--", lw=1.2, label="Model simulation", alpha=0.8)
    ax.set_ylabel("Temperature (°C)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_title(f"Temperature  R²={temp_params['r2']:.3f}  "
                 f"(heater: {temp_params['a_heater']/RESAMPLE_S*60:+.3f}°C/min, "
                 f"exhaust: {temp_params['a_exhaust']/RESAMPLE_S*60:+.3f}°C/min, "
                 f"passive τ={1/temp_params['a_passive']:.0f} intervals)", fontsize=9)

    # RH
    ax = axes[1]
    ax.plot(sample_1m.index, sample_1m["avg_rh"], "b-",  lw=1.5, label="Actual avg RH", alpha=0.8)
    ax.plot(sample_1m.index, sample_1m["rh_sim"], "r--", lw=1.2, label="Model simulation", alpha=0.8)
    ax.set_ylabel("Relative Humidity (%)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_title(f"Humidity  R²={rh_params['r2']:.3f}  "
                 f"(exhaust: {rh_params['b_exhaust']/RESAMPLE_S*60:+.3f}%/min, "
                 f"passive τ={1/max(0.0001,rh_params['b_passive']):.0f} intervals)", fontsize=9)

    # Device states
    ax = axes[2]
    ax.fill_between(sample_1m.index, 0, sample_1m["heater"],  alpha=0.5, color="red",  label="Heater on")
    ax.fill_between(sample_1m.index, 0, sample_1m["exhaust"], alpha=0.5, color="blue", label="Exhaust on")
    ax.set_ylabel("Device state")
    ax.set_ylim(-0.1, 1.3)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout()
    out_path = os.path.join(output_dir, "mpc_validation.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    log(f"  Saved validation plot → {out_path}")

    # Residual histogram
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle("Model Residuals (one-step-ahead prediction errors)", fontsize=12)

    temp_resid = df_sim["avg_temp"] - df_sim["temp_sim"]
    rh_resid   = df_sim["avg_rh"]   - df_sim["rh_sim"]

    axes[0].hist(temp_resid.dropna(), bins=60, color="steelblue", edgecolor="white", linewidth=0.3)
    axes[0].set_xlabel("Temperature residual (°C)")
    axes[0].set_ylabel("Count")
    axes[0].set_title(f"Temp: mean={temp_resid.mean():.3f}°C  std={temp_resid.std():.3f}°C")
    axes[0].axvline(0, color="red", lw=1.5, ls="--")
    axes[0].grid(True, alpha=0.3)

    axes[1].hist(rh_resid.dropna(), bins=60, color="teal", edgecolor="white", linewidth=0.3)
    axes[1].set_xlabel("RH residual (%)")
    axes[1].set_ylabel("Count")
    axes[1].set_title(f"RH: mean={rh_resid.mean():.3f}%  std={rh_resid.std():.3f}%")
    axes[1].axvline(0, color="red", lw=1.5, ls="--")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(output_dir, "mpc_residuals.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    log(f"  Saved residuals plot  → {out_path}")


def print_results(temp_params: dict, rh_params: dict, resample_s: int, warnings: list[str]) -> None:
    """Print fitted parameters in a human-readable and copy-pasteable format."""
    iv = resample_s / 60.0  # interval in minutes

    print()
    print("=" * 70)
    print("  MPC MODEL PARAMETERS")
    print("=" * 70)
    print()
    print(f"  Ambient estimates:")
    print(f"    Ambient temperature : {temp_params['temp_amb']:.1f} °C")
    print(f"    Ambient RH          : {rh_params['rh_amb']:.1f} %")
    print()
    print(f"  Temperature model  (R² = {temp_params['r2']:.4f}):")
    print(f"    Heater effect       : {temp_params['a_heater']:+.5f} °C/interval  "
          f"({temp_params['a_heater']/iv:+.3f} °C/min)")
    print(f"    Exhaust effect      : {temp_params['a_exhaust']:+.5f} °C/interval  "
          f"({temp_params['a_exhaust']/iv:+.3f} °C/min)")
    print(f"    Passive coefficient : {temp_params['a_passive']:+.5f} /interval  "
          f"(τ ≈ {1/max(0.0001,temp_params['a_passive'])*iv:.1f} min to ambient)")
    print(f"    Bias                : {temp_params['a_bias']:+.5f} °C/interval")
    print()
    print(f"  Humidity model  (R² = {rh_params['r2']:.4f}):")
    print(f"    Exhaust effect      : {rh_params['b_exhaust']:+.5f} %/interval  "
          f"({rh_params['b_exhaust']/iv:+.3f} %/min)")
    print(f"    Passive coefficient : {rh_params['b_passive']:+.5f} /interval  "
          f"(τ ≈ {1/max(0.0001,rh_params['b_passive'])*iv:.1f} min to ambient)")
    print(f"    Bias                : {rh_params['b_bias']:+.5f} %/interval")
    print()

    if warnings:
        print("  ⚠️  WARNINGS:")
        for w in warnings:
            print(f"    {w}")
        print()

    quality_temp = "✅ Good" if temp_params["r2"] > 0.5 else ("⚠️  Moderate" if temp_params["r2"] > 0.2 else "❌ Poor")
    quality_rh   = "✅ Good" if rh_params["r2"]   > 0.5 else ("⚠️  Moderate" if rh_params["r2"]   > 0.2 else "❌ Poor")
    print(f"  Model quality:")
    print(f"    Temperature fit : {quality_temp} (R²={temp_params['r2']:.3f})")
    print(f"    Humidity fit    : {quality_rh}   (R²={rh_params['r2']:.3f})")
    print()
    print("  NOTE: R² for one-step-ahead delta prediction is typically lower")
    print("  than for level prediction — values above 0.3 are reasonable.")
    print("  Check the validation plots (mpc_validation.png) for visual fit quality.")
    print()
    print("  ─" * 35)
    print("  PASTE THESE INTO YOUR CONTROLLER CONFIG:")
    print("  ─" * 35)
    print()
    print("  # MPC model parameters — generated by mpc_identify.py")
    print(f"  mpc_temp_amb:     {temp_params['temp_amb']:.2f}   # °C")
    print(f"  mpc_rh_amb:       {rh_params['rh_amb']:.2f}   # %")
    print(f"  mpc_a_heater:     {temp_params['a_heater']:.6f}   # °C/interval")
    print(f"  mpc_a_exhaust:    {temp_params['a_exhaust']:.6f}   # °C/interval")
    print(f"  mpc_a_passive:    {temp_params['a_passive']:.6f}   # /interval")
    print(f"  mpc_a_bias:       {temp_params['a_bias']:.6f}   # °C/interval")
    print(f"  mpc_b_exhaust:    {rh_params['b_exhaust']:.6f}   # %/interval")
    print(f"  mpc_b_passive:    {rh_params['b_passive']:.6f}   # /interval")
    print(f"  mpc_b_bias:       {rh_params['b_bias']:.6f}   # %/interval")
    print()
    print("=" * 70)


def main():
    print()
    print("MPC Model Identification — Small Grow Tent Controller")
    print("=" * 70)
    print()

    # Validate config
    if not os.path.exists(HA_DB_PATH):
        print(f"ERROR: Database not found at '{HA_DB_PATH}'")
        print("Edit HA_DB_PATH in the CONFIGURATION section of this script.")
        sys.exit(1)

    since = datetime.now(tz=timezone.utc) - timedelta(days=HISTORY_DAYS)
    log(f"Loading {HISTORY_DAYS} days of history from {HA_DB_PATH}")
    log(f"Since: {since.strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    conn = sqlite3.connect(f"file:{HA_DB_PATH}?mode=ro", uri=True)

    log("Loading entity histories...")
    try:
        canopy_temp = load_entity_history(conn, ENTITY_CANOPY_TEMP, since)
        top_temp    = load_entity_history(conn, ENTITY_TOP_TEMP,    since)
        canopy_rh   = load_entity_history(conn, ENTITY_CANOPY_RH,   since)
        top_rh      = load_entity_history(conn, ENTITY_TOP_RH,      since)
        heater      = load_entity_history(conn, ENTITY_HEATER,      since)
        exhaust     = load_entity_history(conn, ENTITY_EXHAUST,     since)
    except ValueError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()

    print()
    log(f"Resampling to {RESAMPLE_S}s intervals...")
    df = build_dataset(canopy_temp, top_temp, canopy_rh, top_rh, heater, exhaust, RESAMPLE_S)
    log(f"  Dataset: {len(df):,} samples spanning "
        f"{(df.index[-1]-df.index[0]).total_seconds()/3600:.1f} hours")
    log(f"  Heater on: {df['heater'].mean()*100:.1f}% of time")
    log(f"  Exhaust on: {df['exhaust'].mean()*100:.1f}% of time")
    log(f"  Avg temp: {df['avg_temp'].mean():.1f}°C  (min {df['avg_temp'].min():.1f}, max {df['avg_temp'].max():.1f})")
    log(f"  Avg RH:   {df['avg_rh'].mean():.1f}%   (min {df['avg_rh'].min():.1f}, max {df['avg_rh'].max():.1f})")

    print()
    log(f"Estimating ambient conditions (p{AMBIENT_PERCENTILE} during exhaust-on periods)...")
    temp_amb, rh_amb = estimate_ambient(df, AMBIENT_PERCENTILE)
    log(f"  Ambient temp estimate: {temp_amb:.1f}°C")
    log(f"  Ambient RH estimate:   {rh_amb:.1f}%")

    print()
    log("Fitting temperature model...")
    temp_params, X_t, y_t, y_t_pred = fit_temperature_model(df, temp_amb)
    log(f"  R² (one-step delta): {temp_params['r2']:.4f}")

    log("Fitting humidity model...")
    rh_params, X_r, y_r, y_r_pred = fit_humidity_model(df, rh_amb)
    log(f"  R² (one-step delta): {rh_params['r2']:.4f}")

    print()
    log("Running open-loop simulation for validation...")
    df_sim = simulate_model(df, temp_params, rh_params)

    # Compute open-loop RMSE over last 24h only
    last_24h = df_sim[df_sim.index >= df_sim.index[-1] - pd.Timedelta(hours=24)]
    temp_rmse = np.sqrt(((last_24h["avg_temp"] - last_24h["temp_sim"])**2).mean())
    rh_rmse   = np.sqrt(((last_24h["avg_rh"]   - last_24h["rh_sim"])**2).mean())
    log(f"  Open-loop RMSE (last 24h): temp={temp_rmse:.2f}°C  RH={rh_rmse:.2f}%")

    print()
    log("Generating validation plots...")
    plot_results(df_sim, temp_params, rh_params, OUTPUT_DIR)

    warnings = make_sanity_checks(temp_params, rh_params, RESAMPLE_S)

    print_results(temp_params, rh_params, RESAMPLE_S, warnings)


if __name__ == "__main__":
    main()
