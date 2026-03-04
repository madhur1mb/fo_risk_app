"""
Stress Testing Engine
=====================
Simulates portfolio P&L under predefined and custom shock scenarios.

Scenarios implemented:
  1. Index Move  : ±1%, ±2%, ±3% spot shock
  2. Vol Spike   : IV +5%, +10%, -5%
  3. Gap Scenario: Combined spot + vol shock (gap-up / gap-down)
  4. Expiry Decay: Theta decay on expiry day (T → 0)
  5. Custom      : Arbitrary Δspot% and Δvol%

Author: F&O Risk Intelligence Team
"""

import math
from typing import Optional
from backend.engines.greeks_engine import bsm_price, compute_greeks, RISK_FREE_RATE, LOT_SIZE_MAP, DEFAULT_LOT_SIZE


# ---------------------------------------------------------------------------
# Core shock function
# ---------------------------------------------------------------------------

def _shocked_pnl(
    positions: list[dict],
    spot_map: dict,
    spot_shock_pct: float = 0.0,
    vol_shock_abs: float = 0.0,
    time_shock_days: float = 0.0,
) -> dict:
    """
    Compute portfolio P&L under a combined shock.

    Parameters
    ----------
    positions       : List of position dicts (pre-enriched with iv, tte, etc.)
    spot_map        : Original spot prices per underlying
    spot_shock_pct  : % change in spot (e.g., -0.02 for -2%)
    vol_shock_abs   : Absolute change in IV (e.g., 0.05 for +5%)
    time_shock_days : Additional calendar days to collapse (theta decay test)

    Returns
    -------
    dict with total_pnl and per-position breakdown
    """
    total_pnl = 0.0
    breakdown = []

    for pos in positions:
        underlying  = pos["underlying"].upper()
        S_orig      = spot_map.get(underlying, 24000)
        S_shocked   = S_orig * (1 + spot_shock_pct)
        sigma_orig  = pos.get("iv", 0.15)
        sigma_shock = max(sigma_orig + vol_shock_abs, 0.005)   # floor at 0.5%
        T_orig      = pos["tte"]
        T_shocked   = max(T_orig - time_shock_days / 365, 0.0)
        K           = pos["strike"]
        option_type = pos["type"].upper()
        qty         = pos["qty"]
        entry       = pos["entry_price"]
        lot_size    = LOT_SIZE_MAP.get(underlying, DEFAULT_LOT_SIZE)

        fair_orig    = bsm_price(S_orig,    K, T_orig,    RISK_FREE_RATE, sigma_orig,  option_type)
        fair_shocked = bsm_price(S_shocked, K, T_shocked, RISK_FREE_RATE, sigma_shock, option_type)

        # P&L = change in position value (entry price is sunk cost for stress test;
        # we measure incremental change from current fair value)
        pnl = (fair_shocked - fair_orig) * qty * lot_size

        total_pnl += pnl
        breakdown.append({
            "underlying":   underlying,
            "type":         option_type,
            "strike":       K,
            "qty":          qty,
            "fair_orig":    round(fair_orig, 2),
            "fair_shocked": round(fair_shocked, 2),
            "pnl":          round(pnl, 2),
        })

    return {
        "total_pnl": round(total_pnl, 2),
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Predefined scenario suite
# ---------------------------------------------------------------------------

SCENARIOS = [
    {"name": "Spot -3%",       "spot_shock_pct": -0.03, "vol_shock_abs":  0.00, "time_shock_days": 0},
    {"name": "Spot -2%",       "spot_shock_pct": -0.02, "vol_shock_abs":  0.00, "time_shock_days": 0},
    {"name": "Spot -1%",       "spot_shock_pct": -0.01, "vol_shock_abs":  0.00, "time_shock_days": 0},
    {"name": "Spot +1%",       "spot_shock_pct":  0.01, "vol_shock_abs":  0.00, "time_shock_days": 0},
    {"name": "Spot +2%",       "spot_shock_pct":  0.02, "vol_shock_abs":  0.00, "time_shock_days": 0},
    {"name": "Spot +3%",       "spot_shock_pct":  0.03, "vol_shock_abs":  0.00, "time_shock_days": 0},
    {"name": "IV Spike +5%",   "spot_shock_pct":  0.00, "vol_shock_abs":  0.05, "time_shock_days": 0},
    {"name": "IV Spike +10%",  "spot_shock_pct":  0.00, "vol_shock_abs":  0.10, "time_shock_days": 0},
    {"name": "IV Crush -5%",   "spot_shock_pct":  0.00, "vol_shock_abs": -0.05, "time_shock_days": 0},
    {"name": "Gap Down -2%+IV","spot_shock_pct": -0.02, "vol_shock_abs":  0.05, "time_shock_days": 0},
    {"name": "Gap Up +2%+IV",  "spot_shock_pct":  0.02, "vol_shock_abs":  0.05, "time_shock_days": 0},
    {"name": "Expiry Decay 1d","spot_shock_pct":  0.00, "vol_shock_abs":  0.00, "time_shock_days": 1},
    {"name": "Expiry Decay 3d","spot_shock_pct":  0.00, "vol_shock_abs":  0.00, "time_shock_days": 3},
    {"name": "Expiry Decay 7d","spot_shock_pct":  0.00, "vol_shock_abs":  0.00, "time_shock_days": 7},
    {"name": "Black Swan -5%+IV+20%","spot_shock_pct": -0.05, "vol_shock_abs": 0.20, "time_shock_days": 0},
]


def run_all_scenarios(positions: list[dict], spot_map: dict) -> list[dict]:
    """
    Run all predefined stress scenarios against the portfolio.

    Parameters
    ----------
    positions : Enriched position list (must include iv, tte, lot_size fields)
    spot_map  : Dict of underlying -> current spot price

    Returns
    -------
    List of scenario results, each with name, total_pnl, and breakdown.
    """
    results = []
    for scenario in SCENARIOS:
        result = _shocked_pnl(
            positions,
            spot_map,
            spot_shock_pct   = scenario["spot_shock_pct"],
            vol_shock_abs    = scenario["vol_shock_abs"],
            time_shock_days  = scenario["time_shock_days"],
        )
        results.append({
            "scenario":  scenario["name"],
            "total_pnl": result["total_pnl"],
            "breakdown": result["breakdown"],
        })
    return results


def run_custom_scenario(
    positions: list[dict],
    spot_map: dict,
    spot_shock_pct: float,
    vol_shock_abs: float,
    time_shock_days: float = 0.0,
) -> dict:
    """
    Run a single user-defined stress scenario.

    Parameters
    ----------
    positions       : Enriched position list
    spot_map        : Underlying -> spot mapping
    spot_shock_pct  : Spot % change as decimal (-0.03 = -3%)
    vol_shock_abs   : Absolute IV change (0.05 = +5 vol points)
    time_shock_days : Days of theta decay to apply

    Returns
    -------
    dict with total_pnl and breakdown
    """
    return _shocked_pnl(
        positions,
        spot_map,
        spot_shock_pct  = spot_shock_pct,
        vol_shock_abs   = vol_shock_abs,
        time_shock_days = time_shock_days,
    )


# ---------------------------------------------------------------------------
# Payoff diagram data generator
# ---------------------------------------------------------------------------

def payoff_diagram(
    positions: list[dict],
    spot_map: dict,
    n_points: int = 100,
    spot_range_pct: float = 0.10,
) -> dict:
    """
    Generate payoff diagram data for the portfolio at expiry.

    Sweeps spot from -spot_range_pct to +spot_range_pct around current spot.

    Parameters
    ----------
    positions      : Enriched position list
    spot_map       : Underlying -> spot mapping
    n_points       : Number of spot price points to evaluate
    spot_range_pct : Half-width of the spot sweep as a fraction (default ±10%)

    Returns
    -------
    dict with x (spot prices, per underlying) and y (total P&L)
    """
    # For simplicity, build a combined payoff using NIFTY reference or first underlying
    if not positions:
        return {"x": [], "y_current": [], "y_expiry": []}

    primary = positions[0]["underlying"].upper()
    S_base  = spot_map.get(primary, 24000)
    spots   = [S_base * (1 + spot_range_pct * (i / (n_points / 2) - 1)) for i in range(n_points + 1)]

    y_expiry  = []
    y_current = []

    for S_test in spots:
        pnl_expiry  = 0.0
        pnl_current = 0.0

        for pos in positions:
            underlying  = pos["underlying"].upper()
            # Scale other underlyings proportionally (simplified)
            scale  = S_test / S_base
            S_pos  = spot_map.get(underlying, 24000) * scale

            K           = pos["strike"]
            option_type = pos["type"].upper()
            qty         = pos["qty"]
            entry       = pos["entry_price"]
            sigma       = pos.get("iv", 0.15)
            T           = pos["tte"]
            lot_size    = LOT_SIZE_MAP.get(underlying, DEFAULT_LOT_SIZE)

            # Expiry P&L (intrinsic only, T=0)
            intrinsic = max(S_pos - K, 0) if option_type == "CE" else max(K - S_pos, 0)
            pnl_expiry += (intrinsic - entry) * qty * lot_size

            # Current theoretical P&L
            fair_current = bsm_price(S_pos, K, T, RISK_FREE_RATE, sigma, option_type)
            pnl_current  += (fair_current - entry) * qty * lot_size

        y_expiry.append(round(pnl_expiry, 2))
        y_current.append(round(pnl_current, 2))

    return {
        "x":         [round(s, 2) for s in spots],
        "y_expiry":  y_expiry,
        "y_current": y_current,
        "base_spot": S_base,
    }
