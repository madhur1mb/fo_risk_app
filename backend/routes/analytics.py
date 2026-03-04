"""
Analytics API Routes
====================
Endpoints for trade-specific analytics, OI charts, IV data.
"""

from flask import Blueprint, request, jsonify
from backend.engines.market_engine    import open_interest_chain, classify_oi_buildup, get_spot
from backend.engines.volatility_engine import iv_intelligence_report, volatility_smile
from backend.engines.market_engine     import get_atm_iv

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/oi-chain/<underlying>", methods=["GET"])
def oi_chain(underlying: str):
    """Return strike-wise OI chain for the given underlying."""
    spot = get_spot(underlying)
    chain = open_interest_chain(underlying.upper(), spot)
    return jsonify(chain)


@analytics_bp.route("/pcr/<underlying>", methods=["GET"])
def pcr(underlying: str):
    """Return Put-Call Ratio for the underlying."""
    spot  = get_spot(underlying)
    chain = open_interest_chain(underlying.upper(), spot)
    buildup = classify_oi_buildup(
        price_change_pct=0.005,   # mock: 0.5% up day
        oi_change_pct=0.08,
    )
    return jsonify({
        "underlying": underlying.upper(),
        "pcr":        chain["pcr"],
        "max_pain":   chain["max_pain"],
        "buildup":    buildup,
    })


@analytics_bp.route("/iv-intelligence/<underlying>", methods=["GET"])
def iv_intelligence(underlying: str):
    """Return full IV intelligence report for one underlying."""
    spot = get_spot(underlying)
    iv   = get_atm_iv(underlying)
    T    = float(request.args.get("T", 30 / 365))
    report = iv_intelligence_report(underlying.upper(), spot, iv, T)
    return jsonify(report)


@analytics_bp.route("/vol-smile/<underlying>", methods=["GET"])
def vol_smile(underlying: str):
    """Return volatility smile data for charting."""
    spot = get_spot(underlying)
    iv   = get_atm_iv(underlying)
    T    = float(request.args.get("T", 30 / 365))
    smile = volatility_smile(underlying.upper(), spot, T, iv)
    return jsonify(smile)
