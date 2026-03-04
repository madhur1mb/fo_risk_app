"""
Portfolio API Routes
====================
Handles CSV upload and returns full portfolio risk metrics.

Endpoints:
  POST /api/portfolio/upload   — upload CSV, get full risk report
  POST /api/portfolio/analyze  — analyze raw JSON positions
  GET  /api/portfolio/sample   — list available sample portfolios
"""

from flask import Blueprint, request, jsonify
import json, os

from backend.utils.portfolio_parser import parse_portfolio_csv, enrich_positions
from backend.engines.greeks_engine   import aggregate_portfolio_greeks, _default_spot
from backend.engines.market_engine   import get_spot_map, get_spot, get_atm_iv
from backend.engines.fragility_engine import fragility_gauge, trade_analytics, estimate_margin
from backend.engines.volatility_engine import iv_intelligence_report
from backend.engines.stress_engine   import payoff_diagram

portfolio_bp = Blueprint("portfolio", __name__)

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "../../sample_portfolios")


# ---------------------------------------------------------------------------
# Upload & analyze CSV
# ---------------------------------------------------------------------------

@portfolio_bp.route("/upload", methods=["POST"])
def upload_portfolio():
    """
    Accept a multipart/form-data or raw CSV upload and return a full risk report.

    Request: multipart form with field 'file' (CSV)
    Response: JSON risk report
    """
    # Support both multipart upload and raw CSV body
    if "file" in request.files:
        f       = request.files["file"]
        content = f.read()
    elif request.data:
        content = request.data
    else:
        return jsonify({"error": "No file provided"}), 400

    positions, errors = parse_portfolio_csv(content)

    if errors and not positions:
        return jsonify({"error": "CSV parsing failed", "details": errors}), 422

    return _build_risk_report(positions, parse_errors=errors)


@portfolio_bp.route("/analyze", methods=["POST"])
def analyze_positions():
    """
    Accept JSON positions and return a risk report.

    Request body:
      { "positions": [ { "underlying": "NIFTY", "type": "CE", ... } ] }
    """
    data = request.get_json(force=True, silent=True) or {}
    positions_raw = data.get("positions", [])

    if not positions_raw:
        return jsonify({"error": "No positions provided"}), 400

    # Parse from dict format (already validated client-side)
    positions = []
    for p in positions_raw:
        from backend.engines.market_engine import time_to_expiry_years
        tte = time_to_expiry_years(p.get("expiry", ""))
        positions.append({
            "underlying":  str(p.get("underlying", "NIFTY")).upper(),
            "type":        str(p.get("type", "CE")).upper(),
            "strike":      float(p.get("strike", 24000)),
            "expiry":      str(p.get("expiry", "")),
            "qty":         int(p.get("qty", 1)),
            "entry_price": float(p.get("entry_price", 0)),
            "tte":         tte,
        })

    return _build_risk_report(positions)


# ---------------------------------------------------------------------------
# Sample portfolios
# ---------------------------------------------------------------------------

@portfolio_bp.route("/samples", methods=["GET"])
def list_samples():
    """Return a list of available sample portfolio files."""
    try:
        files = [f for f in os.listdir(SAMPLES_DIR) if f.endswith(".csv")]
        return jsonify({"samples": sorted(files)})
    except FileNotFoundError:
        return jsonify({"samples": []})


@portfolio_bp.route("/sample/<name>", methods=["GET"])
def load_sample(name: str):
    """Load and analyze a named sample portfolio CSV."""
    safe_name = os.path.basename(name)
    path      = os.path.join(SAMPLES_DIR, safe_name)
    if not os.path.exists(path):
        return jsonify({"error": f"Sample '{safe_name}' not found"}), 404

    with open(path, "rb") as fh:
        content = fh.read()

    positions, errors = parse_portfolio_csv(content)
    return _build_risk_report(positions, parse_errors=errors, source=safe_name)


# ---------------------------------------------------------------------------
# Internal: build the full risk report
# ---------------------------------------------------------------------------

def _build_risk_report(
    positions: list[dict],
    parse_errors: list[str] = [],
    source: str = "user_upload",
) -> tuple:
    """
    Core function that computes the complete risk report for a portfolio.

    Steps:
      1. Get live/simulated spot prices
      2. Enrich positions with IV
      3. Compute aggregate Greeks
      4. Compute Fragility Score
      5. Compute IV intelligence per underlying
      6. Build payoff diagram
      7. Compile stress scenarios (deferred — done in /api/stress)

    Returns Flask response tuple.
    """
    underlyings = list({p["underlying"] for p in positions})
    spot_map    = get_spot_map(underlyings)

    # Enrich with IV
    enriched = enrich_positions(positions, spot_map)

    # Aggregate Greeks
    greeks = aggregate_portfolio_greeks(enriched, spot_map)

    # Trade-level analytics
    for pos in greeks["positions"]:
        S = spot_map.get(pos["underlying"], 24000)
        pos["analytics"] = trade_analytics(pos, S)

    # Fragility gauge
    fragility = fragility_gauge(
        enriched,
        spot_map,
        net_delta = greeks["net_delta"],
        net_gamma = greeks["net_gamma"],
        net_theta = greeks["net_theta"],
        net_vega  = greeks["net_vega"],
    )

    # IV intelligence per underlying
    iv_reports = {}
    for u in underlyings:
        S = spot_map.get(u, 24000)
        iv = get_atm_iv(u)
        T  = min((p["tte"] for p in enriched if p["underlying"] == u), default=30/365)
        iv_reports[u] = iv_intelligence_report(u, S, iv, T)

    # Payoff diagram
    payoff = payoff_diagram(enriched, spot_map)

    # Summary P&L
    total_mtm = sum(p["mtm_pnl"] for p in greeks["positions"])

    # Net / Gross Exposure
    gross_exp = sum(
        abs(p["qty"]) * spot_map.get(p["underlying"], 24000) * p.get("lot_size", 50)
        for p in greeks["positions"]
    )
    net_exp   = sum(
        p["qty"] * spot_map.get(p["underlying"], 24000) * p.get("lot_size", 50)
        for p in greeks["positions"]
    )

    response = {
        "source":          source,
        "position_count":  len(enriched),
        "underlyings":     underlyings,
        "spot_map":        spot_map,
        "greeks": {
            "net_delta": greeks["net_delta"],
            "net_gamma": greeks["net_gamma"],
            "net_theta": greeks["net_theta"],
            "net_vega":  greeks["net_vega"],
        },
        "exposure": {
            "gross_inr": round(gross_exp, 2),
            "net_inr":   round(net_exp, 2),
        },
        "total_mtm_pnl":  round(total_mtm, 2),
        "positions":      greeks["positions"],
        "fragility":      fragility,
        "iv_intelligence": iv_reports,
        "payoff_diagram": payoff,
        "parse_warnings": parse_errors or [],
    }

    return jsonify(response), 200
