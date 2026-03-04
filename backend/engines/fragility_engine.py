"""
Fragility Gauge Engine
======================
Computes a composite 0–100 fragility score for the portfolio.

Score components:
  1. Gamma Exposure (30%) — how much the delta can shift on a 1% move
  2. Vega Concentration (25%) — IV sensitivity relative to portfolio size
  3. Margin Utilization (25%) — capital at risk relative to limit
  4. Theta Decay Pressure (10%) — daily time decay as % of portfolio value
  5. Correlation Risk (10%) — cross-underlying concentration

Color states:
  0–30   : GREEN  (Low Risk)
  31–60  : YELLOW (Moderate Risk)
  61–80  : ORANGE (High Risk)
  81–100 : RED    (Critical Risk)

Author: F&O Risk Intelligence Team
"""

import math
from backend.engines.greeks_engine import LOT_SIZE_MAP, DEFAULT_LOT_SIZE

# ---------------------------------------------------------------------------
# Margin estimation (simplified SPAN-proxy)
# ---------------------------------------------------------------------------

MARGIN_RATE = {          # % of notional required as initial margin (approximate)
    "NIFTY":      0.11,
    "BANKNIFTY":  0.13,
    "FINNIFTY":   0.12,
    "MIDCPNIFTY": 0.14,
    "SENSEX":     0.11,
}
DEFAULT_MARGIN_RATE = 0.12


def estimate_margin(positions: list[dict], spot_map: dict) -> float:
    """
    Estimate total margin requirement using SPAN-proxy (% of notional).

    In production this would come from the broker's SPAN calculator.

    Parameters
    ----------
    positions : Enriched position list
    spot_map  : underlying -> spot

    Returns
    -------
    float: Estimated margin in INR
    """
    total_margin = 0.0
    for pos in positions:
        underlying = pos["underlying"].upper()
        S          = spot_map.get(underlying, 24000)
        lot_size   = LOT_SIZE_MAP.get(underlying, DEFAULT_LOT_SIZE)
        qty        = abs(pos["qty"])    # gross lots
        rate       = MARGIN_RATE.get(underlying, DEFAULT_MARGIN_RATE)
        notional   = S * lot_size * qty
        total_margin += notional * rate
    return round(total_margin, 2)


def portfolio_notional(positions: list[dict], spot_map: dict) -> float:
    """Compute total gross notional across all positions."""
    total = 0.0
    for pos in positions:
        underlying = pos["underlying"].upper()
        S          = spot_map.get(underlying, 24000)
        lot_size   = LOT_SIZE_MAP.get(underlying, DEFAULT_LOT_SIZE)
        total     += S * lot_size * abs(pos["qty"])
    return round(total, 2)


# ---------------------------------------------------------------------------
# Component scorers (each returns 0–100)
# ---------------------------------------------------------------------------

def _gamma_score(net_gamma: float, net_delta: float, spot: float = 24000) -> float:
    """
    Score based on gamma exposure relative to portfolio delta.
    High gamma = delta can swing wildly on moves → dangerous for short gamma.

    A net_gamma of 0.01 means delta changes by 0.01 per 1-point move in spot.
    We normalise by scaling against a 1% spot move.
    """
    gamma_exposure_1pct = abs(net_gamma) * (spot * 0.01)   # delta change on 1% move
    delta_reference     = max(abs(net_delta), 1)
    ratio               = gamma_exposure_1pct / delta_reference
    # Empirical: ratio > 0.5 → very high gamma risk for the delta size
    score = min(ratio * 200, 100)
    return round(score, 1)


def _vega_score(net_vega: float, portfolio_value: float) -> float:
    """
    Score based on vega relative to portfolio size.
    A 1 vol-point move in IV changes P&L by net_vega.
    """
    if portfolio_value <= 0:
        return 50.0
    vega_pct = abs(net_vega) / portfolio_value * 100    # % impact for 1 vol point
    # >3% impact for 1 vol point = high concentration
    score = min(vega_pct * 33, 100)
    return round(score, 1)


def _margin_score(used_margin: float, capital: float) -> float:
    """
    Score based on margin utilization.
    60% utilization = moderate risk; 90%+ = critical.
    """
    if capital <= 0:
        return 70.0
    utilization_pct = (used_margin / capital) * 100
    if utilization_pct >= 90:
        return 100.0
    elif utilization_pct >= 70:
        return 70 + (utilization_pct - 70) * 1.5
    else:
        return utilization_pct
    

def _theta_score(net_theta: float, portfolio_value: float) -> float:
    """
    Score based on daily theta decay as % of portfolio value.
    Positive theta (net short options) is NOT penalized; negative theta IS.
    """
    if net_theta >= 0:
        return 0.0          # earning theta → no fragility from decay
    daily_decay_pct = abs(net_theta) / max(portfolio_value, 1) * 100
    score = min(daily_decay_pct * 100, 100)
    return round(score, 1)


def _correlation_score(positions: list[dict]) -> float:
    """
    Score based on cross-underlying concentration.
    More unique underlyings = lower score (diversified).
    """
    underlyings = set(pos["underlying"].upper() for pos in positions)
    n = len(underlyings)
    if n == 0:
        return 100.0
    elif n == 1:
        return 80.0     # concentrated in one index
    elif n == 2:
        return 50.0
    elif n == 3:
        return 30.0
    else:
        return 10.0     # well diversified


# ---------------------------------------------------------------------------
# Composite Fragility Gauge
# ---------------------------------------------------------------------------

WEIGHTS = {
    "gamma":       0.30,
    "vega":        0.25,
    "margin":      0.25,
    "theta":       0.10,
    "correlation": 0.10,
}

RISK_STATES = [
    (81, 100, "CRITICAL", "#ef4444"),
    (61,  80, "HIGH",     "#f97316"),
    (31,  60, "MODERATE", "#eab308"),
    ( 0,  30, "LOW",      "#22c55e"),
]


def fragility_gauge(
    positions: list[dict],
    spot_map: dict,
    net_delta: float,
    net_gamma: float,
    net_theta: float,
    net_vega:  float,
    capital:   float = 2_000_000,   # Default ₹20L capital assumption
) -> dict:
    """
    Compute the composite Fragility Gauge score.

    Parameters
    ----------
    positions : Enriched position list
    spot_map  : underlying -> spot
    net_delta : Portfolio net delta
    net_gamma : Portfolio net gamma
    net_theta : Portfolio net theta (daily)
    net_vega  : Portfolio net vega
    capital   : Trader's capital allocation (INR); defaults to ₹20L

    Returns
    -------
    dict with:
      score        : 0–100 composite score
      state        : "LOW" / "MODERATE" / "HIGH" / "CRITICAL"
      color        : Hex color for UI display
      components   : Dict of individual component scores and weights
      margin_used  : Estimated margin (INR)
      margin_pct   : Margin as % of capital
      portfolio_val: Gross notional
    """
    if not positions:
        return {"score": 0, "state": "LOW", "color": "#22c55e", "components": {}}

    margin_used   = estimate_margin(positions, spot_map)
    port_notional = portfolio_notional(positions, spot_map)
    portfolio_val = max(port_notional, 1)

    # Representative spot for gamma scoring (use first underlying)
    primary_spot = spot_map.get(positions[0]["underlying"].upper(), 24000)

    comp_scores = {
        "gamma":       _gamma_score(net_gamma, net_delta, primary_spot),
        "vega":        _vega_score(net_vega, portfolio_val),
        "margin":      _margin_score(margin_used, capital),
        "theta":       _theta_score(net_theta, portfolio_val),
        "correlation": _correlation_score(positions),
    }

    composite = sum(WEIGHTS[k] * v for k, v in comp_scores.items())
    composite  = round(min(composite, 100), 1)

    # Determine risk state
    state, color = "LOW", "#22c55e"
    for lo, hi, label, hex_color in RISK_STATES:
        if lo <= composite <= hi:
            state = label
            color = hex_color
            break

    return {
        "score":         composite,
        "state":         state,
        "color":         color,
        "components":    {
            k: {"score": v, "weight": WEIGHTS[k], "contribution": round(WEIGHTS[k] * v, 2)}
            for k, v in comp_scores.items()
        },
        "margin_used":   margin_used,
        "margin_pct":    round((margin_used / capital) * 100, 2),
        "portfolio_val": portfolio_val,
        "capital":       capital,
    }


# ---------------------------------------------------------------------------
# Risk-Reward & Trade Analytics
# ---------------------------------------------------------------------------

def trade_analytics(pos: dict, spot: float) -> dict:
    """
    Compute trade-level analytics for a single position.

    Parameters
    ----------
    pos  : Enriched position dict
    spot : Current spot price

    Returns
    -------
    dict with breakeven, pop, risk_reward_ratio
    """
    from backend.engines.greeks_engine import bsm_price, RISK_FREE_RATE
    from backend.engines.greeks_engine import LOT_SIZE_MAP, DEFAULT_LOT_SIZE
    import math
    from scipy.stats import norm

    underlying  = pos["underlying"].upper()
    K           = pos["strike"]
    option_type = pos["type"].upper()
    qty         = pos["qty"]
    entry       = pos["entry_price"]
    T           = pos["tte"]
    sigma       = pos.get("iv", 0.15)
    lot_size    = LOT_SIZE_MAP.get(underlying, DEFAULT_LOT_SIZE)

    # Break-even at expiry
    if option_type == "CE":
        be = K + entry if qty > 0 else K - entry
    else:
        be = K - entry if qty > 0 else K + entry

    # Probability of Profit (PoP) — log-normal at expiry
    # PoP = P(spot > BE at expiry) for long call, etc.
    if T > 0 and sigma > 0:
        d = (math.log(spot / be) + (RISK_FREE_RATE - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        if option_type == "CE":
            pop = norm.cdf(d) if qty > 0 else norm.cdf(-d)
        else:
            pop = norm.cdf(-d) if qty > 0 else norm.cdf(d)
    else:
        intrinsic = max(spot - K, 0) if option_type == "CE" else max(K - spot, 0)
        pop       = 1.0 if intrinsic > entry else 0.0

    # Risk-reward (simple: max profit / max loss for defined-risk trades)
    max_profit = entry * abs(qty) * lot_size   # for short: premium received
    max_loss   = entry * abs(qty) * lot_size   # for long: premium paid
    rr_ratio   = 1.0  # simplified; real calculation needs strategy context

    return {
        "breakeven":      round(be, 2),
        "pop":            round(pop * 100, 2),   # %
        "max_profit_inr": round(max_profit, 2),
        "max_loss_inr":   round(max_loss, 2),
        "rr_ratio":       round(rr_ratio, 2),
    }
