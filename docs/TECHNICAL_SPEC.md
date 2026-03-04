# RiskPulse — F&O Risk Intelligence Platform
## Technical Specification & Architecture Document

---

## 1. Product Vision

RiskPulse is a real-time risk intelligence dashboard for active Indian F&O
derivatives traders. It ingests the trader's open positions via a CSV file
and provides comprehensive risk analytics, volatility intelligence, market
positioning context, and stress-testing capabilities.

---

## 2. MVP Feature Set

### Phase 1 (MVP — This Release)
| Module | Feature | Status |
|---|---|---|
| Portfolio Ingestion | CSV upload, validation, parsing | ✅ |
| Greeks Engine | Delta, Gamma, Theta, Vega (BSM) | ✅ |
| Fragility Gauge | Composite 0–100 risk score | ✅ |
| IV Intelligence | IV Rank, IV Pct, HV, IV-HV Spread | ✅ |
| Volatility Smile | Parametric skew model | ✅ |
| OI Heatmap | Strike-wise Call/Put OI | ✅ |
| Payoff Diagram | Current + expiry P&L curves | ✅ |
| Stress Testing | 15 predefined + 1 custom scenario | ✅ |
| Trade Analytics | PoP, Break-even per position | ✅ |
| Exposure Metrics | Gross/Net notional, Margin est. | ✅ |

### Phase 2 (Future)
- Live NSE data feed integration (broker API / NSE bhav copy)
- Sharpe Ratio & Drawdown (requires trade history)
- Real SPAN margin calculation
- Equity curve / P&L history tracking
- WebSocket-based live Greek updates

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    BROWSER (SPA)                        │
│  HTML + CSS + Vanilla JS + Chart.js                     │
│  ├─ Upload Zone (CSV drag-drop)                         │
│  ├─ Dashboard (Greeks, Fragility, Charts)               │
│  └─ Stress Test Panel                                   │
└────────────────────┬────────────────────────────────────┘
                     │ REST / JSON
┌────────────────────▼────────────────────────────────────┐
│                 FLASK API LAYER                          │
│  /api/portfolio/upload   → full risk report             │
│  /api/portfolio/sample/* → load sample CSV              │
│  /api/stress/run         → stress scenarios             │
│  /api/analytics/oi-chain → OI chain data                │
│  /api/analytics/iv-*     → IV intelligence              │
│  /api/market/overview    → index snapshot               │
└────────────────────┬────────────────────────────────────┘
                     │ Python function calls
┌────────────────────▼────────────────────────────────────┐
│              COMPUTATION ENGINES                        │
│                                                         │
│  greeks_engine.py   : BSM pricing, Greeks, IV solver   │
│  stress_engine.py   : Scenario shocks, Payoff diagram   │
│  volatility_engine.py: IV Rank/Pct, HV, Smile          │
│  fragility_engine.py: Composite risk score              │
│  market_engine.py   : OI chain, PCR, spot data         │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Computational Modules

### 4.1 Greeks Engine (`greeks_engine.py`)
- **Model**: Black-Scholes-Merton (European options)
- **Greeks**: Delta, Gamma, Theta (daily), Vega (per 1% IV), Rho
- **IV Solver**: Brent's method (robust vs Newton-Raphson for boundary cases)
- **Lot sizes**: NSE standard (NIFTY=50, BANKNIFTY=15, etc.)
- **Note**: BSM is appropriate for index European options (no early exercise)

### 4.2 Stress Engine (`stress_engine.py`)
- **15 predefined scenarios**: spot shocks (±1/2/3%), IV shocks (+5/10/-5%),
  gap combos, theta decay (1/3/7 days), black swan
- **Custom scenario**: arbitrary Δspot%, ΔIV vol-points, Δdays
- **Payoff diagram**: 100-point spot sweep ±10% with current + expiry P&L

### 4.3 Volatility Engine (`volatility_engine.py`)
- **IV Rank**: (Current − 52w Low) / (52w High − Low) × 100
- **IV Percentile**: % of days in history below current IV
- **Realized Vol**: Close-to-close log returns, 20-day rolling, annualised
- **Smile model**: SSVI-inspired parametric skew (slope + curvature)
  - OTM puts carry vol premium (negative skew typical in Indian markets)

### 4.4 Fragility Engine (`fragility_engine.py`)
- **5 components** with weights:
  - Gamma exposure (30%): delta instability on 1% move
  - Vega concentration (25%): IV sensitivity / portfolio size
  - Margin utilization (25%): used margin / capital
  - Theta pressure (10%): daily decay for long option holders
  - Correlation risk (10%): cross-underlying concentration
- **Output**: 0–100 score + color-coded state (LOW/MODERATE/HIGH/CRITICAL)

### 4.5 Market Engine (`market_engine.py`)
- **OI chain**: Log-normal OI profile with realistic skew
- **PCR**: Put-Call Ratio from aggregated chain OI
- **Max Pain**: Strike minimising total option buyer payoff
- **OI Classification**: 4-quadrant (Long Buildup / Short Buildup /
  Short Covering / Long Unwinding)

---

## 5. Data Model

### Position CSV Schema
```
underlying : str  — NIFTY | BANKNIFTY | FINNIFTY | MIDCPNIFTY | SENSEX
type       : str  — CE | PE
strike     : float — Strike price (INR)
expiry     : str   — YYYY-MM-DD (NSE expiry date)
qty        : int   — Lots (negative = short position)
entry_price: float — Premium paid/received (INR per unit)
```

### Enriched Position (Internal)
```python
{
  ...csv_fields,
  "tte":            float,   # time to expiry in years
  "iv":             float,   # implied volatility (decimal)
  "spot":           float,   # current underlying spot
  "fair_value":     float,   # BSM theoretical value
  "mtm_pnl":        float,   # mark-to-market P&L (INR)
  "delta":          float,   # position delta (qty × lot × unit delta)
  "gamma":          float,
  "theta":          float,
  "vega":           float,
  "delta_per_unit": float,
  "lot_size":       int,
  "analytics": {
    "breakeven":    float,
    "pop":          float,   # probability of profit (%)
    ...
  }
}
```

---

## 6. UI Layout Structure

```
┌─ TOP NAV ───────────────────────────────────────────────┐
│  Brand | Market Ticker (NIFTY/BN/FIN/VIX) | IST Clock  │
├─────────────────────────────────────────────────────────┤
│  UPLOAD ZONE (when no portfolio loaded)                 │
│    CSV drag-drop | Sample portfolio picker              │
├─────────────────────────────────────────────────────────┤
│  DASHBOARD HEADER: Title | Positions count | Actions   │
├─────────────────────────────────────────────────────────┤
│  ROW 1: [Delta][Gamma][Theta][Vega] | [FRAGILITY GAUGE]│
├─────────────────────────────────────────────────────────┤
│  ROW 2: [MTM P&L][Gross Exp][Net Exp][Margin %]        │
├─────────────────────────────────────────────────────────┤
│  ROW 3: [Payoff Diagram] [OI Heatmap] [Vol Smile]      │
├─────────────────────────────────────────────────────────┤
│  IV INTELLIGENCE CARDS (one per underlying)             │
├─────────────────────────────────────────────────────────┤
│  STRESS TEST GRID (15 scenario cards + custom form)     │
├─────────────────────────────────────────────────────────┤
│  POSITIONS TABLE (full detail + analytics per leg)      │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Key Assumptions

1. **Options type**: All options are European (BSM applicable for NSE index options)
2. **Risk-free rate**: RBI repo rate proxy at 6.8% p.a.
3. **Margin**: SPAN-proxy using flat % of notional (production = broker SPAN API)
4. **Capital**: ₹20L default trader capital for margin utilisation calculation
5. **Market data**: Simulated using mean-reverting OU process (production = live feed)
6. **Lot sizes**: NSE standard as of 2025 (NIFTY=50, BANKNIFTY=15, FINNIFTY=40)

---

## 8. Running the App

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py

# Open browser at
http://localhost:5000
```

---

## 9. Directory Structure

```
fo_risk_app/
├── app.py                          # Flask app factory & entry point
├── requirements.txt
├── README.md
├── backend/
│   ├── engines/
│   │   ├── greeks_engine.py        # BSM pricing & Greeks
│   │   ├── stress_engine.py        # Stress scenarios & payoff
│   │   ├── volatility_engine.py    # IV analytics & smile
│   │   ├── fragility_engine.py     # Risk scoring & trade analytics
│   │   └── market_engine.py        # OI chain, PCR, spot data
│   ├── routes/
│   │   ├── portfolio.py            # /api/portfolio/*
│   │   ├── analytics.py            # /api/analytics/*
│   │   ├── stress.py               # /api/stress/*
│   │   └── market.py               # /api/market/*
│   └── utils/
│       └── portfolio_parser.py     # CSV validation & enrichment
├── frontend/
│   ├── templates/index.html        # SPA shell
│   └── static/
│       ├── css/style.css           # Dark terminal design system
│       └── js/app.js               # Dashboard logic & charts
├── sample_portfolios/
│   ├── 01_iron_condor_nifty.csv
│   ├── 02_bull_call_spread_banknifty.csv
│   ├── 03_short_straddle_nifty.csv
│   ├── 04_multi_index_mixed.csv
│   └── 05_naked_short_puts_aggressive.csv
└── docs/
    └── TECHNICAL_SPEC.md           # This document
```
