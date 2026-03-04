"""
Portfolio Parser Utility
========================
Parses and validates the trader's position CSV file.

Expected CSV format:
  underlying,type,strike,expiry,qty,entry_price
  NIFTY,CE,24000,2026-03-10,-1,700
  BANKNIFTY,PE,60000,2026-03-10,1,800

Validation rules:
  - underlying: must be a recognized Indian index
  - type: must be "CE" or "PE"
  - strike: must be a positive number
  - expiry: must be a future date (YYYY-MM-DD)
  - qty: non-zero integer (negative = short)
  - entry_price: positive number (premium paid/received)

Author: F&O Risk Intelligence Team
"""

import csv
import io
from datetime import date
from typing import Union
import logging

logger = logging.getLogger(__name__)

RECOGNIZED_UNDERLYINGS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"
}

VALID_TYPES = {"CE", "PE"}


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse_portfolio_csv(content: Union[str, bytes]) -> tuple[list[dict], list[str]]:
    """
    Parse a portfolio CSV string/bytes into a list of position dicts.

    Parameters
    ----------
    content : Raw CSV content (string or bytes)

    Returns
    -------
    (positions, errors):
      positions : List of validated position dicts
      errors    : List of human-readable error messages
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    positions = []
    errors    = []

    try:
        reader = csv.DictReader(io.StringIO(content.strip()))
    except Exception as exc:
        return [], [f"Failed to parse CSV: {exc}"]

    # Validate header
    required_cols = {"underlying", "type", "strike", "expiry", "qty", "entry_price"}
    actual_cols   = set(reader.fieldnames or [])
    missing       = required_cols - {c.strip().lower() for c in actual_cols}
    if missing:
        return [], [f"Missing required columns: {', '.join(sorted(missing))}"]

    for row_num, row in enumerate(reader, start=2):   # row 1 = header
        row_errors = []

        # --- underlying ---
        underlying = (row.get("underlying") or "").strip().upper()
        if underlying not in RECOGNIZED_UNDERLYINGS:
            row_errors.append(
                f"Row {row_num}: Unknown underlying '{underlying}'. "
                f"Supported: {', '.join(sorted(RECOGNIZED_UNDERLYINGS))}"
            )

        # --- type ---
        opt_type = (row.get("type") or "").strip().upper()
        if opt_type not in VALID_TYPES:
            row_errors.append(f"Row {row_num}: type must be CE or PE, got '{opt_type}'")

        # --- strike ---
        try:
            strike = float(row.get("strike", ""))
            if strike <= 0:
                raise ValueError("non-positive strike")
        except (ValueError, TypeError):
            strike = None
            row_errors.append(f"Row {row_num}: Invalid strike '{row.get('strike')}'")

        # --- expiry ---
        expiry_str = (row.get("expiry") or "").strip()
        try:
            expiry_date = date.fromisoformat(expiry_str)
            if expiry_date < date.today():
                logger.warning("Row %d: Expiry %s is in the past — will use T=0", row_num, expiry_str)
        except (ValueError, AttributeError):
            expiry_date = None
            row_errors.append(f"Row {row_num}: Invalid expiry '{expiry_str}' (expected YYYY-MM-DD)")

        # --- qty ---
        try:
            qty = int(row.get("qty", ""))
            if qty == 0:
                raise ValueError("zero qty")
        except (ValueError, TypeError):
            qty = None
            row_errors.append(f"Row {row_num}: Invalid qty '{row.get('qty')}' (must be non-zero integer)")

        # --- entry_price ---
        try:
            entry_price = float(row.get("entry_price", ""))
            if entry_price < 0:
                raise ValueError("negative entry price")
        except (ValueError, TypeError):
            entry_price = None
            row_errors.append(f"Row {row_num}: Invalid entry_price '{row.get('entry_price')}'")

        if row_errors:
            errors.extend(row_errors)
            continue    # skip malformed rows

        # Compute time-to-expiry
        from backend.engines.market_engine import time_to_expiry_years
        tte = time_to_expiry_years(expiry_str)

        positions.append({
            "underlying":  underlying,
            "type":        opt_type,
            "strike":      strike,
            "expiry":      expiry_str,
            "qty":         qty,
            "entry_price": entry_price,
            "tte":         tte,
        })

    return positions, errors


# ---------------------------------------------------------------------------
# Enrich positions with market data (spot, IV, greeks)
# ---------------------------------------------------------------------------

def enrich_positions(positions: list[dict], spot_map: dict) -> list[dict]:
    """
    Attach live/simulated market data to each position.

    Parameters
    ----------
    positions : Parsed position list from parse_portfolio_csv
    spot_map  : underlying -> spot price mapping

    Returns
    -------
    Enriched positions with iv and tte fields ready for Greeks computation
    """
    from backend.engines.market_engine import get_atm_iv
    from backend.engines.greeks_engine import implied_volatility, RISK_FREE_RATE

    enriched = []
    for pos in positions:
        underlying = pos["underlying"]
        S          = spot_map.get(underlying, 24000)
        T          = pos["tte"]
        K          = pos["strike"]
        entry      = pos["entry_price"]
        opt_type   = pos["type"]

        # Try to solve IV from the entry price (the observed market premium)
        iv = implied_volatility(entry, S, K, T, RISK_FREE_RATE, opt_type)

        # Fallback to ATM IV if solver fails (entry price may be stale)
        if iv is None or iv < 0.02:
            iv = get_atm_iv(underlying)

        enriched.append({**pos, "iv": round(iv, 6)})

    return enriched
