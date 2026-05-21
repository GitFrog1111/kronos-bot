# NOBLE HQ — AUTONOMOUS WORK STATE
## Current Priorities (updated 2026-05-21 10:15 UTC)

### ✅ P0 — Data Pipeline (kronos-bot) — ALL FIXED, AWAITS RESTART
1. **Confidence scaling** — ✅ Exponential formula `0.5 + 0.48*(1 - e^(-8x))`. Maps 0.05% → 0.658, 0.10% → 0.764, 0.20% → 0.883.
2. **Market odds accuracy** — ✅ Extracts `outcomePrices` from Gamma API (e.g. [0.505, 0.495]) directly. CLOB only as fallback.
3. **Price history endpoint** — ✅ 50 real Binance 5m candles via `/api/price_history`.
4. **Odds staleness indicator** — ✅ `is_fallback` flag flows through API → Dashboard shows ✓ LIVE or ⚠ FALLBACK badge.

### ✅ P1 — Dashboard (noble-hq) — ALL RESOLVED
5. **ProjectsView** — ✅ Live from `/api/performance` + `/api/status`.
6. **StatusPanel** — ✅ Derives missions from `/api/status` + `/api/trades`.
7. **OpsFeed** — ✅ Derives events from `/api/trades` + `/api/current_signal`.
8. **MetricsBar** — ✅ Live from `/api/performance` + `/api/status`.
9. **Confidence display** — ✅ Multiplies by 100.
10. **Prediction graph** — ✅ Real sparkline from price history close prices.

### 🔴 Bot Restart Required
Both critical fixes (odds + confidence) are in source files but need bot restart.
**Current status**: Open position (Trade #31, Down, $3). DO NOT restart until position resolves.

### 📊 Model Sensitivity Analysis (COMPLETE)
- BTC 5-min volatility: median |Δ| = 0.035%, max = 0.181%
- Kronos prediction (0.038%) is well-calibrated to actual volatility
- 100% of 5-min moves are <0.2% — BTC is stable at this timescale
- New exponential formula properly maps this range: 0.05% → 65.8% confidence

### 💾 Commit Status
- kronos-bot: 2 commits pending push (confidence+odds fix, is_fallback pipeline)
- noble-hq: 1 commit pending push (is_fallback indicator in dashboard)
- **User must push**: `cd /workspace/kronos-bot && git push origin main` and `cd /workspace/noble-hq && git push origin main`
- No GitHub credentials on container

### 🟢 Bot State (Live, Healthy)
- Balance: $113.00 (+16%, 30 trades, 60% win rate)
- Current position: Down $3 (Trade #31, open since 09:40 UTC)
- Model loaded, 500 candles, 50 in price history
- Cloudflared tunnel active
- All 8 API endpoints responding

## NOBLE Team Status
- **Emile-A239** — ✅ Confidence/odds fixes (committed)
- **Jorge-052** — ✅ Dashboard all-live, odds badge, built & committed
- **Kat-B320** — ✅ Model sensitivity analysis complete
- **Carter-A259** — ✅ Orchestration, commits, state tracking
