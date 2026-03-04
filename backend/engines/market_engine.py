"""
Market Data Engine
==================
Provides simulated (but realistic) market data for:
  - Current spot prices
  - ATM implied volatility
  - Open Interest (OI) by strike
  - Put-Call Ratio (PCR)
  - OI change vs price change classification

In a production system, live data would come from:
  - NSE Data API / Bhav copy for OI
  - Broker WebSocket / NSE feed for live prices and IV

Author: F&O Risk Intelligence Team
"""

import random
import math
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Simulated spot prices (seeded for consistency within a session)
# ---------------------------------------------------------------------------

_BASE_SPOTS = {
    "NIFTY":      24150,
    "BANKNIFTY":  51250,
    "FINNIFTY":   23100,
    "MIDCPNIFTY": 12350,
    "SENSEX":     79500,
}

_BASE_ATM_IV = {
    "NIFTY":      0.138,
    "BANKNIFTY":  0.185,
    "FINNIFTY":   0.172,
    "MIDCPNIFTY": 0.205,
    "SENSEX":     0.135,
}


def get_spot(underlying: str) -> float:
    """Return the current simulated spot price for an underlying."""
    base = _BASE_SPOTS.get(underlying.upper(), 24000)
    # Add small deterministic noise (±0.3%) to simulate live market
    rng  = random.Random(int(date.today().toordinal()) + hash(underlying) % 100)
    noise = rng.uniform(-0.003, 0.003)
    return round(base * (1 + noise), 2)


def get_atm_iv(underlying: str) -> float:
    """Return simulated ATM IV for an underlying."""
    base = _BASE_ATM_IV.get(underlying.upper(), 0.15)
    rng  = random.Random(int(date.today().toordinal() * 7) + hash(underlying) % 100)
    noise = rng.uniform(-0.01, 0.01)
    return round(max(base + noise, 0.05), 6)


def get_spot_map(underlyings: list[str]) -> dict:
    """Build a spot map for all required underlyings."""
    return {u.upper(): get_spot(u) for u in underlyings}


# ---------------------------------------------------------------------------
# Open Interest generator
# ---------------------------------------------------------------------------

def _oi_for_strike(
    spot: float,
    K: float,
    option_type: str,
    atm_oi: float,
    rng: random.Random,
) -> int:
    """
    Generate realistic OI for a given strike using a log-normal profile
    centered at ATM with a downside skew (puts have higher OTM OI).

    Parameters
    ----------
    spot        : Current spot price
    K           : Strike price
    option_type : "CE" or "PE"
    atm_oi      : ATM OI reference level (lots)
    rng         : Seeded random generator

    Returns
    -------
    int: Open Interest in contracts (lots)
    """
    moneyness = (K - spot) / spot    # positive = above spot

    if option_type == "CE":
        # Calls: peak near ATM, fall off on OTM calls
        center = 0.01       # slight OTM tendency
        width  = 0.04
    else:
        # Puts: peak slightly ITM/ATM, heavier skew toward OTM puts
        center = -0.01
        width  = 0.05

    # Gaussian profile around center
    profile = math.exp(-0.5 * ((moneyness - center) / width) ** 2)
    # Add randomness (± 30%)
    noise   = rng.uniform(0.7, 1.3)
    oi = int(atm_oi * profile * noise)
    return max(oi, 100)     # minimum 100 lots


def open_interest_chain(
    underlying: str,
    spot: float,
    n_strikes: int = 11,
    step_pct: float = 0.005,
    seed: int = 1,
) -> dict:
    """
    Generate a full OI chain for an underlying around the current spot.

    Parameters
    ----------
    underlying  : Index name
    spot        : Current spot price
    n_strikes   : Number of strikes above and below ATM
    step_pct    : Strike step as % of spot (0.5% default → ~120 points for NIFTY 24k)
    seed        : RNG seed

    Returns
    -------
    dict with strikes, call_oi, put_oi, call_oi_change, put_oi_change, pcr
    """
    rng = random.Random(seed + hash(underlying) % 999)
    atm_ref = _BASE_SPOTS.get(underlying.upper(), spot)

    # Round spot to nearest standard strike (100 for NIFTY, 100 for BN)
    step_abs = round(spot * step_pct, -2)
    step_abs = max(step_abs, 100)

    # ATM strike (nearest round number)
    atm_k = round(spot / step_abs) * step_abs

    strikes = [atm_k + (i - n_strikes) * step_abs for i in range(n_strikes * 2 + 1)]

    # OI levels (ATM ≈ 50k–200k lots depending on index)
    atm_oi_map = {
        "NIFTY": 80000, "BANKNIFTY": 50000, "FINNIFTY": 30000,
        "MIDCPNIFTY": 20000, "SENSEX": 40000,
    }
    atm_oi = atm_oi_map.get(underlying.upper(), 50000)

    call_oi   = [_oi_for_strike(spot, K, "CE", atm_oi, rng) for K in strikes]
    put_oi    = [_oi_for_strike(spot, K, "PE", atm_oi, rng) for K in strikes]

    # OI change (simulate yesterday's vs today's OI)
    rng2 = random.Random(seed + hash(underlying) % 777)
    call_oi_chg = [int(c * rng2.uniform(-0.15, 0.20)) for c in call_oi]
    put_oi_chg  = [int(p * rng2.uniform(-0.15, 0.20)) for p in put_oi]

    total_call_oi = sum(call_oi)
    total_put_oi  = sum(put_oi)
    pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else 1.0

    # Max Pain: strike where option buyers lose the most
    max_pain_k = _max_pain(strikes, call_oi, put_oi)

    return {
        "underlying":     underlying,
        "spot":           spot,
        "strikes":        strikes,
        "call_oi":        call_oi,
        "put_oi":         put_oi,
        "call_oi_change": call_oi_chg,
        "put_oi_change":  put_oi_chg,
        "pcr":            pcr,
        "total_call_oi":  total_call_oi,
        "total_put_oi":   total_put_oi,
        "max_pain":       max_pain_k,
    }


def _max_pain(strikes: list, call_oi: list, put_oi: list) -> float:
    """
    Compute max pain strike: spot level that minimizes total option buyer payoff.
    """
    pain = []
    for K_expiry in strikes:
        total = 0
        for K, c_oi, p_oi in zip(strikes, call_oi, put_oi):
            call_pain = max(K_expiry - K, 0) * c_oi
            put_pain  = max(K - K_expiry, 0) * p_oi
            total += call_pain + put_pain
        pain.append(total)
    min_idx = pain.index(min(pain))
    return strikes[min_idx]


# ---------------------------------------------------------------------------
# OI Build-up classification
# ---------------------------------------------------------------------------

def classify_oi_buildup(
    price_change_pct: float,
    oi_change_pct: float,
) -> dict:
    """
    Classify OI vs price action into 4 quadrants used by market participants.

    Quadrant logic (standard NSE interpretation):
    ┌─────────────┬──────────────────────────────────────────────┐
    │ Price ↑ OI ↑│ Long Buildup  — bullish signal               │
    │ Price ↓ OI ↑│ Short Buildup — bearish signal               │
    │ Price ↑ OI ↓│ Short Covering — bearish trend weakening     │
    │ Price ↓ OI ↓│ Long Unwinding — bullish trend weakening     │
    └─────────────┴──────────────────────────────────────────────┘

    Parameters
    ----------
    price_change_pct : % price change (positive = up)
    oi_change_pct    : % OI change   (positive = OI increased)

    Returns
    -------
    dict with classification, description, sentiment, and strength
    """
    price_up = price_change_pct > 0
    oi_up    = oi_change_pct > 0

    if price_up and oi_up:
        cls  = "Long Buildup"
        desc = "New longs being added; bullish momentum"
        sent = "BULLISH"
    elif not price_up and oi_up:
        cls  = "Short Buildup"
        desc = "New shorts being added; bearish momentum"
        sent = "BEARISH"
    elif price_up and not oi_up:
        cls  = "Short Covering"
        desc = "Shorts being covered; rally may lack conviction"
        sent = "NEUTRAL-BULLISH"
    else:
        cls  = "Long Unwinding"
        desc = "Longs being exited; fall may lack conviction"
        sent = "NEUTRAL-BEARISH"

    # Strength based on magnitude
    strength = min(abs(price_change_pct) + abs(oi_change_pct), 10) / 10

    return {
        "classification": cls,
        "description":    desc,
        "sentiment":      sent,
        "strength":       round(strength, 2),
    }


def time_to_expiry_years(expiry_str: str) -> float:
    """
    Compute time to expiry in years from today.

    Parameters
    ----------
    expiry_str : Date string in YYYY-MM-DD format

    Returns
    -------
    float: Years to expiry (can be 0.0 if expired)
    """
    try:
        expiry = date.fromisoformat(expiry_str)
        today  = date.today()
        delta  = (expiry - today).days
        return max(delta / 365.0, 0.0)
    except (ValueError, TypeError):
        return 30 / 365.0   # fallback: 30 days
