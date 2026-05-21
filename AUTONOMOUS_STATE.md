# NOBLE HQ — AUTONOMOUS WORK STATE
## Current Priorities (updated 2026-05-21 18:00 UTC)

### 🔴 P0 — $100 Polymarket Profit (PRIMARY MISSION)
**Target:** $100 settled profit from Polymarket BTC 5-min markets
**Current:** $12.58 settled profit (98 trades, 51% WR, Sharpe 0.0165)
**Gap:** $87.42 remaining

Key issues to fix:
1. **Confidence calibration broken** — 84% predicted confidence vs 51% actual win rate. Overconfident.
2. **Edge extraction** — Kronos model needs signal quality improvement or ensemble approach
3. **Kelly sizing** — Bet sizes based on inflated confidence → overbetting
4. **Market selection** — May need to skip low-liquidity or thin-orderbook markets

Action plan:
- Analyze trade history to find actual edge per confidence bin
- Recalibrate confidence → actual probability mapping
- Tighten Kelly fraction or switch to fractional Kelly (k=0.1-0.15)
- Consider adding technical indicators (RSI divergence, volume profile) as signal filters
- Backtest any changes before deploying

### ⬜ P1 — Hyperliquid Trading Bot
- Dry-run perpetual futures bot (BTC-USD)
- Coinbase spot price feed
- Momentum + mean reversion hybrid

### ✅ P2 — Kronos BTC 5m (MAINTENANCE)
- Bot running, API healthy on port 8500
- Dashboard live with Supabase realtime
- Build loop automated (every 30 min)

### ✅ INFRASTRUCTURE
- Bot API: http://localhost:8500 (healthy)
- Cloudflare tunnel: active, serves dashboard
- Noble HQ SPA: Supabase realtime live, pushed to GitHub (4def78b)
- Auto mode: cron every hour (job 73ee68d1da46), toggled via auto_mode.flag
- Supabase tables: pending user migration (4 tables + directive)

## NOBLE Team Assignments
- **Kat-B320** — Analyze trade history, find actual edge, recalibrate confidence model
- **Emile-A239** — Implement signal quality improvements, backtest rapidly
- **Carter-A259** — Orchestration, deploy changes, report to Noble Six
- **Jorge-052** — Infrastructure, bot stability, dashboard updates
