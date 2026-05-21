# NOBLE HQ — AUTONOMOUS WORK STATE
## Current Priorities (updated 2026-05-21 10:10 UTC)

### ✅ P0 — Data Pipeline (kronos-bot)
1. **Confidence scaling** — FIXED: Exponential formula `0.5 + 0.48*(1 - e^(-8x))` replaces quadratic. Maps 0.038% → ~0.63. Takes effect on bot restart.
2. **Market odds accuracy** — FIXED: `polymarket_client.py` now extracts `outcomePrices` from Gamma API (e.g. ["0.505", "0.495"]) directly. CLOB fallback only when missing. `_parse_token_ids_from_market` fixed (outcomes are strings, not dicts). Takes effect on bot restart.
3. **Price history endpoint** — DONE: `/api/price_history` returns 50 real Binance candles. Dashboard renders live sparkline from it.

### ✅ P1 — Dashboard (noble-hq)
4. **ProjectsView** — DONE: Fetches from `/api/performance` + `/api/status`.
5. **StatusPanel** — DONE: Derives missions from `/api/status` + `/api/trades`.
6. **OpsFeed** — DONE: Derives events from `/api/trades` + `/api/current_signal`.
7. **MetricsBar** — DONE: Fetches from `/api/performance` + `/api/status`.
8. **Confidence display bug** — FIXED: `KronosDashboard.tsx` already multiplies by 100.
9. **Prediction graph** — DONE: Real sparkline from `/api/price_history` close prices.

### 🔶 P1 — Remaining
10. **Model sensitivity**: Kronos predicts tiny moves (0.01-0.15%). Even with new formula, low change_pct caps confidence. Investigate if model architecture or input features can produce larger deltas.
11. **Odds staleness indicator**: Dashboard should show when odds are fallback 50/50 vs live Polymarket data.
12. **Bot restart needed**: Both fixes (confidence + odds) require bot restart to take effect. Current open position (Trade #31, Down, $3) — DO NOT restart until resolved.

### 🔴 P2 — Infrastructure
13. **GitHub push**: No credentials on container — user must push: `cd /workspace/kronos-bot && git push origin main`
14. **Commit pending**: noble-hq (check for uncommitted changes)
15. **Build**: noble-hq builds successfully (80 modules, 382KB JS)

## Active Processes
- Bot: PID 47540, localhost:8500, healthy
- Cloudflared: PIDs 15555, 17020, tunnel active
- Noble HQ dev: PID 13374 (Vite), dev mode on port 5173

## Bot State (Live)
- Balance: $113.00 (+16%, 30 trades, 60% win rate)
- Current position: Down $3 (Trade #31, open since 09:40 UTC)
- Market: btc-updown-5m-1779357900 (odds fallback 50/50 until restart)
- Confidence: 0.5194 (will improve to ~0.63 after restart with new formula)

## NOBLE Team Assignment
- **Emile** — ✅ Confidence + Polymarket fixes (committed)
- **Jorge** — Dashboard ready (all live API, built)
- **Kat** — Investigate: Kronos model sensitivity (why such tiny predictions?)
- **Carter** — Orchestration, commit/push, state tracking
