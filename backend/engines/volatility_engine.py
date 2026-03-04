"""
Volatility Intelligence Engine
================================
Provides IV analytics, IV Rank, IV Percentile, Realized Volatility,
and Volatility Smile data generation.

In a production system, IV history would come from a tick database
(e.g., NSE bhav copy or vendor API). Here we use seeded synthetic data
that is realistic for Indian index options.

Author: F&O Risk Intelligence Team
"""

import math
import random
import numpy as np
from datetime import date, timedelta
from typing import Optional
from backend.engines.greeks_engine import implied_volatility, RISK_FREE_RATE

# ---------------------------------------------------------------------------
# Synthetic IV history generator (placeholder for live data feed)
# ---------------------------------------------------------------------------

_IV_PROFILE = {
    "NIFTY":      {"base": 0.14, "mean_revert": 0.16, "std": 0.03},
    "BANKNIFTY":  {"base": 0.18, "mean_revert": 0.20, "std": 0.04},
    "FINNIFTY":   {"base": 0.17, "mean_revert": 0.19, "std": 0.035},
    "MIDCPNIFTY": {"base": 0.20, "mean_revert": 0.22, "std": 0.05},
    "SENSEX":     {"base": 0.14, "mean_revert": 0.16, "std": 0.03},
}


def _generate_iv_history(underlying: str, lookback_days: int = 252, seed: int = 42) -> list[float]:
    """
    Generate a synthetic 1-year daily IV history using mean-reverting OU process.

    Parameters
    ----------
    underlying    : Index name
    lookback_days : Number of trading days to simulate
    seed          : Random seed for reproducibility

    Returns
    -------
    List of daily IV values (decimal)
    """
    rng    = random.Random(seed + hash(underlying) % 1000)
    prof   = _IV_PROFILE.get(underlying.upper(), _IV_PROFILE["NIFTY"])
    mu     = prof["mean_revert"]
    sigma  = prof["std"]
    theta  = 0.15      # mean-reversion speed
    dt     = 1 / 252

    iv = prof["base"]
    history = []
    for _ in range(lookback_days):
        dW = rng.gauss(0, 1) * math.sqrt(dt)
        iv = iv + theta * (mu - iv) * dt + sigma * math.sqrt(iv) * dW
        iv = max(iv, 0.05)   # floor at 5% to avoid degenerate values
        history.append(round(iv, 6))
    return history


# ---------------------------------------------------------------------------
# IV Rank & Percentile
# ---------------------------------------------------------------------------

def iv_rank(current_iv: float, iv_history: list[float]) -> float:
    """
    Compute IV Rank: how today's IV compares to the 52-week high-low range.

    IV Rank = (Current IV − 52w Low) / (52w High − 52w Low) × 100

    Returns
    -------
    float: 0–100, higher = IV is elevated vs history
    """
    if not iv_history:
        return 50.0
    low  = min(iv_history)
    high = max(iv_history)
    if high == low:
        return 50.0
    return round(((current_iv - low) / (high - low)) * 100, 2)


def iv_percentile(current_iv: float, iv_history: list[float]) -> float:
    """
    Compute IV Percentile: fraction of days in history where IV was below current.

    Returns
    -------
    float: 0–100 percentile rank
    """
    if not iv_history:
        return 50.0
    below = sum(1 for iv in iv_history if iv < current_iv)
    return round((below / len(iv_history)) * 100, 2)


# ---------------------------------------------------------------------------
# Realized Volatility (HV)
# ---------------------------------------------------------------------------

def realized_volatility(
    price_series: list[float],
    window: int = 20,
    annualize: bool = True,
) -> Optional[float]:
    """
    Compute Historical/Realized Volatility using close-to-close log returns.

    Parameters
    ----------
    price_series : List of daily closing prices (oldest first)
    window       : Rolling window in days (default 20)
    annualize    : Multiply by √252 to express as annual volatility

    Returns
    -------
    float: HV as decimal, or None if insufficient data
    """
    if len(price_series) < window + 1:
        return None
    prices = price_series[-(window + 1):]
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    mean_ret = sum(log_returns) / len(log_returns)
    variance = sum((r - mean_ret) ** 2 for r in log_returns) / (len(log_returns) - 1)
    hv = math.sqrt(variance)
    if annualize:
        hv *= math.sqrt(252)
    return round(hv, 6)


def _synthetic_price_series(underlying: str, spot: float, days: int = 60, seed: int = 99) -> list[float]:
    """Generate synthetic price history for HV calculation."""
    rng = random.Random(seed + hash(underlying) % 500)
    prof = _IV_PROFILE.get(underlying.upper(), _IV_PROFILE["NIFTY"])
    daily_vol = prof["base"] / math.sqrt(252)
    prices = [spot]
    for _ in range(days):
        ret = rng.gauss(0, daily_vol)
        prices.insert(0, prices[0] * math.exp(ret))
    return list(reversed(prices))


# ---------------------------------------------------------------------------
# Volatility Smile generator
# ---------------------------------------------------------------------------

def volatility_smile(
    underlying: str,
    spot: float,
    T: float,
    atm_iv: float,
    n_strikes: int = 11,
    strike_width_pct: float = 0.05,
) -> dict:
    """
    Generate a volatility smile / skew curve for a given expiry.

    Uses a simplified parametric skew model common in Indian index markets:
    - OTM puts carry a vol premium (negative skew)
    - OTM calls carry a smaller premium

    Parameters
    ----------
    underlying      : Index name
    spot            : Current spot price
    T               : Time to expiry (years)
    atm_iv          : ATM implied volatility (decimal)
    n_strikes       : Number of strikes to generate (odd number recommended)
    strike_width_pct: % distance between adjacent strikes

    Returns
    -------
    dict with strikes, call_ivs, put_ivs, and moneyness labels
    """
    half = n_strikes // 2
    strikes   = []
    call_ivs  = []
    put_ivs   = []
    moneyness = []

    # Skew parameters (empirically calibrated to NSE index options)
    skew_slope   = -0.15      # IV increases as we go lower (negative skew)
    smile_curv   = 0.10       # Smile curvature (smile effect)
    put_premium  = 0.02       # Additional premium for OTM puts

    for i in range(-half, half + 1):
        K = round(spot * (1 + i * strike_width_pct / half), 0)
        strikes.append(K)

        moneyness_ratio = K / spot         # > 1 = OTM call, < 1 = OTM put
        log_m = math.log(moneyness_ratio)  # 0 at ATM

        # SSVI-inspired skew: σ(k) = σ_atm + slope*k + curvature*k²
        skew_adj = skew_slope * log_m + smile_curv * log_m ** 2

        # Put IV: add extra premium for downside protection demand
        put_iv_adj  = skew_adj + (put_premium if i < 0 else 0)
        call_iv_adj = skew_adj

        call_iv = max(atm_iv + call_iv_adj, 0.05)
        put_iv  = max(atm_iv + put_iv_adj,  0.05)

        call_ivs.append(round(call_iv * 100, 2))   # express as %
        put_ivs.append(round(put_iv  * 100, 2))

        if i < 0:
            moneyness.append(f"{K:.0f} (OTM P)")
        elif i == 0:
            moneyness.append(f"{K:.0f} (ATM)")
        else:
            moneyness.append(f"{K:.0f} (OTM C)")

    return {
        "strikes":   strikes,
        "call_ivs":  call_ivs,
        "put_ivs":   put_ivs,
        "moneyness": moneyness,
    }


# ---------------------------------------------------------------------------
# Full IV intelligence report for a given underlying
# ---------------------------------------------------------------------------

def iv_intelligence_report(
    underlying: str,
    spot: float,
    atm_iv: float,
    T: float,
) -> dict:
    """
    Compose a complete IV intelligence report for one underlying.

    Parameters
    ----------
    underlying : Index name
    spot       : Current spot
    atm_iv     : Current ATM IV (decimal)
    T          : Time to nearest expiry (years)

    Returns
    -------
    dict with iv_rank, iv_pct, realized_vol, iv_hv_spread, smile, iv_history
    """
    history = _generate_iv_history(underlying)
    price_series = _synthetic_price_series(underlying, spot)

    rank    = iv_rank(atm_iv, history)
    pct     = iv_percentile(atm_iv, history)
    hv_20   = realized_volatility(price_series, window=20) or atm_iv
    hv_10   = realized_volatility(price_series, window=10) or atm_iv

    smile   = volatility_smile(underlying, spot, T, atm_iv)

    # Build a 60-day IV history for the sparkline chart
    recent_iv = history[-60:]

    return {
        "underlying":    underlying,
        "current_iv":    round(atm_iv * 100, 2),           # %
        "iv_rank":       rank,
        "iv_percentile": pct,
        "hv_20d":        round(hv_20 * 100, 2),
        "hv_10d":        round(hv_10 * 100, 2),
        "iv_hv_spread":  round((atm_iv - hv_20) * 100, 2), # IV premium over HV
        "smile":         smile,
        "iv_history_60d": [round(v * 100, 2) for v in recent_iv],
    }
