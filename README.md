# ⚡ RiskPulse — F&O Risk Intelligence Dashboard

A real-time risk intelligence platform for active Indian F&O derivatives traders.
Upload your positions CSV and get instant Greeks, stress tests, IV analytics, and a fragility score.

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run
python app.py

# 3. Open browser
http://localhost:5000
```

## 📊 CSV Format

```csv
underlying,type,strike,expiry,qty,entry_price
NIFTY,CE,24000,2026-03-27,-2,310
BANKNIFTY,PE,51000,2026-03-27,1,800
```

- **qty negative** = short position
- Supported underlyings: `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `SENSEX`
- Expiry format: `YYYY-MM-DD`

## 🧪 Sample Portfolios

Five pre-built portfolios are included under `sample_portfolios/`:

| File | Strategy |
|---|---|
| `01_iron_condor_nifty.csv` | NIFTY Iron Condor (neutral strategy) |
| `02_bull_call_spread_banknifty.csv` | BankNIFTY Bull Call Spread |
| `03_short_straddle_nifty.csv` | NIFTY Short Straddle (high theta) |
| `04_multi_index_mixed.csv` | Multi-leg, multi-index complex book |
| `05_naked_short_puts_aggressive.csv` | Naked short puts (high margin/risk) |

## 📐 What It Computes

| Feature | Details |
|---|---|
| Greeks | Delta, Gamma, Theta, Vega via Black-Scholes-Merton |
| IV | Implied volatility solved per position (Brent method) |
| IV Rank / Pct | 252-day simulated history |
| Fragility Score | 0–100 composite (gamma + vega + margin + theta + correlation) |
| Stress Tests | 15 scenarios + custom (spot shock + IV spike + theta decay) |
| Payoff Diagram | At-expiry + current BSM P&L across spot range |
| OI Chain | Strike-wise Call/Put OI with PCR & Max Pain |
| Vol Smile | Parametric skew model (SSVI-inspired) |

## 🏗 Architecture

See `docs/TECHNICAL_SPEC.md` for full architecture, module descriptions, and data models.

## ⚠️ Disclaimers

- Market data is **simulated** (seeded synthetic). Connect a live NSE/broker feed for production.
- Margin estimates use a SPAN-proxy (% of notional). Use broker SPAN API for accuracy.
- BSM model is appropriate for European index options only.
- **Not financial advice.**
