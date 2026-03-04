"""
Greeks Engine — Black-Scholes Options Pricing & Greeks Calculator
=================================================================
Implements the Black-Scholes-Merton (BSM) model to compute:
  - Option fair value (call / put)
  - First-order Greeks  : Delta, Gamma, Theta, Vega, Rho
  - Implied Volatility   : Newton-Raphson bisection solver

All inputs use standard financial conventions:
  - Spot / Strike in nominal INR (e.g., 24000 for NIFTY)
  - Time to expiry (T) in years
  - Volatility (σ) and risk-free rate (r) as decimals (e.g., 0.15 for 15%)
  - Option type: "CE" = call, "PE" = put

Author: F&O Risk Intelligence Team
"""

import math
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from typing import Literal, Optional
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RISK_FREE_RATE   = 0.068          # RBI repo rate proxy (6.8 %)
TRADING_DAYS     = 252            # Calendar convention for Indian markets
LOT_SIZE_MAP     = {              # Standard lot sizes (NSE)
    "NIFTY":     50,
    "BANKNIFTY": 15,
    "FINNIFTY":  40,
    "MIDCPNIFTY":75,
    "SENSEX":    10,
}
DEFAULT_LOT_SIZE = 50


# ---------------------------------------------------------------------------
# Internal BSM helpers
# ---------------------------------------------------------------------------

def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Compute the d1 parameter of the BSM model."""
    if T <= 0 or sigma <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Compute the d2 parameter of the BSM model."""
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def bsm_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["CE", "PE"],
) -> float:
    """
    Compute the Black-Scholes-Merton fair value of a European option.

    Parameters
    ----------
    S           : Current underlying spot price (INR)
    K           : Strike price (INR)
    T           : Time to expiry in years
    r           : Risk-free interest rate (decimal)
    sigma       : Implied / historical volatility (decimal)
    option_type : "CE" for call, "PE" for put

    Returns
    -------
    float : Theoretical option premium (INR per unit)
    """
    if T <= 0:
        # At expiry: intrinsic value only
        return max(S - K, 0) if option_type == "CE" else max(K - S, 0)

    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)

    if option_type == "CE":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------

def compute_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: Literal["CE", "PE"],
    qty: int = 1,
    underlying: str = "NIFTY",
) -> dict:
    """
    Compute all first-order Greeks for a single option position.

    Parameters
    ----------
    S           : Spot price
    K           : Strike price
    T           : Time to expiry (years)
    r           : Risk-free rate (decimal)
    sigma       : Volatility (decimal)
    option_type : "CE" or "PE"
    qty         : Number of lots (negative = short)
    underlying  : Name of the underlying (used for lot-size lookup)

    Returns
    -------
    dict with keys: delta, gamma, theta, vega, rho, fair_value, lot_size
    """
    lot_size = LOT_SIZE_MAP.get(underlying.upper(), DEFAULT_LOT_SIZE)
    multiplier = qty * lot_size          # signed, accounts for short positions

    if T <= 0 or sigma <= 0:
        intrinsic = bsm_price(S, K, T, r, sigma, option_type)
        return {
            "delta": (1.0 if option_type == "CE" else -1.0) * multiplier,
            "gamma": 0.0,
            "theta": 0.0,
            "vega":  0.0,
            "rho":   0.0,
            "fair_value": intrinsic,
            "lot_size": lot_size,
        }

    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    pdf_d1 = norm.pdf(d1)
    sqrt_T = math.sqrt(T)

    # ---- Raw per-unit Greeks ----
    gamma_raw = pdf_d1 / (S * sigma * sqrt_T)

    # Delta: probability adjusted
    delta_raw = norm.cdf(d1) if option_type == "CE" else norm.cdf(d1) - 1.0

    # Theta: daily decay (divide annual by 365)
    if option_type == "CE":
        theta_raw = (
            -(S * pdf_d1 * sigma) / (2 * sqrt_T)
            - r * K * math.exp(-r * T) * norm.cdf(d2)
        ) / 365
    else:
        theta_raw = (
            -(S * pdf_d1 * sigma) / (2 * sqrt_T)
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
        ) / 365

    # Vega: change in price per 1% vol move
    vega_raw = S * sqrt_T * pdf_d1 / 100

    # Rho: change in price per 1% rate move
    if option_type == "CE":
        rho_raw = K * T * math.exp(-r * T) * norm.cdf(d2) / 100
    else:
        rho_raw = -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100

    fair_value = bsm_price(S, K, T, r, sigma, option_type)

    return {
        "delta":      round(delta_raw * multiplier, 4),
        "gamma":      round(gamma_raw * multiplier, 6),
        "theta":      round(theta_raw * multiplier, 2),
        "vega":       round(vega_raw  * multiplier, 2),
        "rho":        round(rho_raw   * multiplier, 4),
        "fair_value": round(fair_value, 2),
        "lot_size":   lot_size,
        # Per-unit Greeks (useful for display)
        "delta_per_unit": round(delta_raw, 4),
        "gamma_per_unit": round(gamma_raw, 6),
    }


# ---------------------------------------------------------------------------
# Implied Volatility Solver
# ---------------------------------------------------------------------------

def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: Literal["CE", "PE"],
    tol: float = 1e-6,
    max_iter: int = 200,
) -> Optional[float]:
    """
    Solve for implied volatility using Brent's method (robust root-finding).

    Parameters
    ----------
    market_price : Observed market premium (INR per unit)
    S            : Spot price
    K            : Strike
    T            : Time to expiry (years)
    r            : Risk-free rate
    option_type  : "CE" or "PE"
    tol          : Convergence tolerance
    max_iter     : Maximum iterations

    Returns
    -------
    float (IV as decimal) or None if no solution found
    """
    if T <= 0 or market_price <= 0:
        return None

    intrinsic = max(S - K, 0) if option_type == "CE" else max(K - S, 0)
    if market_price < intrinsic:
        logger.warning("Market price %.2f below intrinsic %.2f", market_price, intrinsic)
        market_price = intrinsic + 0.01   # small adjustment

    def objective(sigma):
        return bsm_price(S, K, T, r, sigma, option_type) - market_price

    try:
        iv = brentq(objective, 1e-6, 10.0, xtol=tol, maxiter=max_iter)
        return round(iv, 6)
    except (ValueError, RuntimeError) as exc:
        logger.debug("IV solver failed for K=%s T=%.4f: %s", K, T, exc)
        return None


# ---------------------------------------------------------------------------
# Portfolio-level Greeks aggregation
# ---------------------------------------------------------------------------

def aggregate_portfolio_greeks(positions: list[dict], spot_map: dict) -> dict:
    """
    Aggregate Greeks across all positions in a portfolio.

    Parameters
    ----------
    positions : List of position dicts (from CSV parser)
    spot_map  : Dict mapping underlying -> current spot price

    Returns
    -------
    dict with net delta, gamma, theta, vega, and per-position greeks
    """
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    position_details = []

    for pos in positions:
        underlying = pos["underlying"].upper()
        S = spot_map.get(underlying, _default_spot(underlying))
        T = pos["tte"]          # time-to-expiry in years, pre-computed
        K = pos["strike"]
        sigma = pos.get("iv", 0.15)
        option_type = pos["type"].upper()
        qty  = pos["qty"]
        entry = pos["entry_price"]

        g = compute_greeks(S, K, T, RISK_FREE_RATE, sigma, option_type, qty, underlying)
        fair = g["fair_value"]
        lot_size = g["lot_size"]

        mtm_pnl = (fair - entry) * qty * lot_size

        pos_detail = {
            **pos,
            **g,
            "spot": S,
            "fair_value": fair,
            "mtm_pnl": round(mtm_pnl, 2),
        }
        position_details.append(pos_detail)

        net["delta"] += g["delta"]
        net["gamma"] += g["gamma"]
        net["theta"] += g["theta"]
        net["vega"]  += g["vega"]

    return {
        "net_delta": round(net["delta"], 4),
        "net_gamma": round(net["gamma"], 6),
        "net_theta": round(net["theta"], 2),
        "net_vega":  round(net["vega"],  2),
        "positions": position_details,
    }


def _default_spot(underlying: str) -> float:
    """Return a sensible default spot for simulation if live feed unavailable."""
    defaults = {
        "NIFTY":      24000,
        "BANKNIFTY":  51000,
        "FINNIFTY":   23000,
        "MIDCPNIFTY": 12000,
        "SENSEX":     79000,
    }
    return defaults.get(underlying, 24000)
