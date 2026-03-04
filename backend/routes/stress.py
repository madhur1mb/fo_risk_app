"""
Stress Test & Market Routes
============================
"""

from flask import Blueprint, request, jsonify
from backend.engines.stress_engine    import run_all_scenarios, run_custom_scenario
from backend.engines.market_engine    import get_spot_map, get_spot, open_interest_chain
from backend.utils.portfolio_parser   import parse_portfolio_csv, enrich_positions

stress_bp = Blueprint("stress", __name__)
market_bp = Blueprint("market",  __name__)


# ---------------------------------------------------------------------------
# Stress Test
# ---------------------------------------------------------------------------

@stress_bp.route("/run", methods=["POST"])
def run_stress():
    """
    Run predefined and optional custom scenario against submitted positions.

    Request body:
      {
        "positions": [...],
        "custom": { "spot_shock_pct": -0.03, "vol_shock_abs": 0.10, "time_shock_days": 0 }
      }
    """
    data = request.get_json(force=True, silent=True) or {}
    raw_positions = data.get("positions", [])
    custom        = data.get("custom")

    if not raw_positions:
        return jsonify({"error": "positions required"}), 400

    # Rebuild enriched positions from raw JSON
    from backend.engines.market_engine import time_to_expiry_years
    positions = []
    for p in raw_positions:
        tte = time_to_expiry_years(p.get("expiry", ""))
        positions.append({**p, "tte": tte})

    underlyings = list({p["underlying"].upper() for p in positions})
    spot_map    = get_spot_map(underlyings)
    enriched    = enrich_positions(positions, spot_map)

    results = run_all_scenarios(enriched, spot_map)

    custom_result = None
    if custom:
        custom_result = run_custom_scenario(
            enriched,
            spot_map,
            spot_shock_pct   = float(custom.get("spot_shock_pct", 0)),
            vol_shock_abs    = float(custom.get("vol_shock_abs", 0)),
            time_shock_days  = float(custom.get("time_shock_days", 0)),
        )

    return jsonify({
        "scenarios":     results,
        "custom_result": custom_result,
    })


# ---------------------------------------------------------------------------
# Market overview
# ---------------------------------------------------------------------------

@market_bp.route("/overview", methods=["GET"])
def market_overview():
    """Return a snapshot of all major Indian index levels and IV."""
    from backend.engines.market_engine import get_atm_iv, _BASE_SPOTS
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
