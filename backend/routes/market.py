"""
Market Data API Routes
========================
Endpoints for market overview and OI data.
"""

from flask import Blueprint, jsonify
from backend.engines.market_engine import get_spot, get_atm_iv, open_interest_chain

market_bp = Blueprint("market", __name__)


@market_bp.route("/overview", methods=["GET"])
def market_overview():
    """Return a snapshot of all major Indian index levels and IV."""
    overview = []
    for underlying in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
        spot = get_spot(underlying)
        iv   = get_atm_iv(underlying)
        overview.append({
            "underlying": underlying,
            "spot":       spot,
            "iv_pct":     round(iv * 100, 2),
        })
    return jsonify({"market": overview})


@market_bp.route("/oi/<underlying>", methods=["GET"])
def market_oi(underlying: str):
    """Return OI chain for the given underlying."""
    spot  = get_spot(underlying)
    chain = open_interest_chain(underlying.upper(), spot)
    return jsonify(chain)
