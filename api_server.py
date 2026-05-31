"""
API Server
FastAPI server on port 8500 exposing bot status, trades, performance,
and current signal endpoints. CORS enabled for localhost:5173 and all origins.
"""

from datetime import datetime, timezone
from typing import Optional
from html import escape

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os

app = FastAPI(title="Kronos BTC Bot", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global references — set by bot.py on startup
_kronos_service = None
_binance_client = None
_polymarket_client = None
_betting_engine = None
_last_prediction: Optional[dict] = None
_last_signal: Optional[dict] = None


def set_services(kronos, binance, polymarket, betting):
    """Register service instances for the API to query."""
    global _kronos_service, _binance_client, _polymarket_client, _betting_engine
    _kronos_service = kronos
    _binance_client = binance
    _polymarket_client = polymarket
    _betting_engine = betting


def update_prediction(prediction: dict) -> None:
    global _last_prediction
    _last_prediction = prediction


def update_signal(signal: dict) -> None:
    global _last_signal
    _last_signal = signal


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _current_status() -> dict:
    """Build a BotStatus-shaped dict from current services."""
    stats = {}
    market = {}
    candle_count = 0
    prediction_summary = None

    if _betting_engine:
        stats = _betting_engine.get_stats()

    if _polymarket_client and _polymarket_client.current_market:
        m = _polymarket_client.current_market
        market = {
            "question": m.get("question", ""),
            "slug": m.get("slug", ""),
            "up_price": m.get("up_price", 0.5),
            "down_price": m.get("down_price", 0.5),
            "start_time": m.get("start_time", ""),
            "end_time": m.get("end_time", ""),
            "is_fallback": m.get("is_fallback", True),
        }

    if _binance_client:
        candle_count = _binance_client.candle_count

    if _last_prediction:
        prediction_summary = {
            "direction": _last_prediction.get("direction"),
            "confidence": _last_prediction.get("confidence"),
            "predicted_close": _last_prediction.get("predicted_close"),
            "predicted_change_pct": _last_prediction.get("predicted_change_pct"),
        }

    position = None
    if _betting_engine and _betting_engine.current_position:
        p = _betting_engine.current_position
        position = {
            "direction": p.get("direction"),
            "amount": p.get("amount"),
            "odds": p.get("odds"),
            "status": p.get("status"),
            "timestamp": p.get("timestamp"),
        }

    up_price = market.get("up_price", 0.5)
    down_price = market.get("down_price", 0.5)
    direction = "none"
    confidence = 0
    rec_bet = None
    rec_dir = None

    if prediction_summary:
        direction = prediction_summary["direction"].lower() if prediction_summary["direction"] else "none"
        confidence = prediction_summary.get("confidence", 0)

    if _last_signal:
        rec_dir = _last_signal.get("direction", "").lower()
        if rec_dir:
            rec_dir = rec_dir if rec_dir in ("up", "down") else None
        rec_bet = _last_signal.get("amount")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "online": True,
        "model_loaded": _kronos_service.is_loaded if _kronos_service else False,
        "candle_count": candle_count,
        "stats": stats,
        "market": market,
        "prediction": prediction_summary,
        "position": position,
        "market_str": market.get("slug", "BTC 5m"),
        "market_time": market.get("start_time", ""),
        "market_close": market.get("end_time", ""),
        "prediction_direction": direction,
        "confidence": confidence,
        "odds_up": up_price,
        "odds_down": down_price,
        "recommended_bet": rec_bet,
        "recommended_direction": rec_dir,
        "is_fallback": market.get("is_fallback", True),
    }


@app.get("/api/status")
async def get_status():
    """
    Current state: balance, P&L, active market, Kronos prediction, position.
    """
    return _current_status()


@app.get("/api/trades")
async def get_trades(limit: int = 20):
    """Recent trades list."""
    if not _betting_engine:
        return {"trades": [], "count": 0}

    trades = _betting_engine.get_recent_trades(limit)
    return {"trades": trades, "count": len(trades)}


@app.get("/api/performance")
async def get_performance():
    """Cumulative P&L, win rate, Sharpe-like metric."""
    if not _betting_engine:
        return {
            "balance": 100.0,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "win_rate": 0,
            "sharpe": 0,
            "total_trades": 0,
        }

    stats = _betting_engine.get_stats()
    return stats


@app.get("/api/current_signal")
async def get_current_signal():
    """Current market odds + Kronos prediction + bet recommendation."""
    market = {}
    prediction = {}
    bet = {}

    if _polymarket_client and _polymarket_client.current_market:
        m = _polymarket_client.current_market
        market = {
            "up_price": m.get("up_price", 0.5),
            "down_price": m.get("down_price", 0.5),
            "up_bid": m.get("up_bid"),
            "up_ask": m.get("up_ask"),
            "question": m.get("question"),
            "slug": m.get("slug"),
        }

    if _last_prediction:
        prediction = {
            "direction": _last_prediction.get("direction"),
            "confidence": _last_prediction.get("confidence"),
            "current_close": _last_prediction.get("current_close"),
            "predicted_close": _last_prediction.get("predicted_close"),
            "predicted_change_pct": _last_prediction.get("predicted_change_pct"),
        }

    if _last_signal:
        bet = _last_signal

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "prediction": prediction,
        "bet_recommendation": bet,
    }


@app.get("/api/health")
async def health_check():
    """Simple health check."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_loaded": _kronos_service.is_loaded if _kronos_service else False,
    }


@app.get("/api/price_history")
async def get_price_history():
    """Return last 50 candles from Binance."""
    if not _binance_client:
        return {"candles": []}

    df = _binance_client.get_recent_candles(50)
    if df.empty:
        return {"candles": []}

    candles = []
    for _, row in df.iterrows():
        candles.append({
            "timestamp": row["timestamps"].isoformat() if hasattr(row["timestamps"], "isoformat") else str(row["timestamps"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })
    return {"candles": candles}


def _downsample_history(history: list[dict], max_points: int = 240) -> list[dict]:
    """Keep the full time span while trimming extremely dense series."""
    if len(history) <= max_points:
        return history

    if max_points < 2:
        return [history[-1]]

    step = (len(history) - 1) / (max_points - 1)
    sampled = []
    seen = set()
    for i in range(max_points):
        idx = round(i * step)
        if idx not in seen:
            sampled.append(history[idx])
            seen.add(idx)
    if sampled[-1] is not history[-1]:
        sampled[-1] = history[-1]
    return sampled


def _build_pnl_svg(history: list[dict]) -> str:
    """Render a compact SVG PnL graph from full balance history."""
    if not history:
        return """<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='320' viewBox='0 0 1200 320'>
  <rect width='100%' height='100%' fill='#07111f'/>
  <text x='60' y='160' fill='#93a4c3' font-family='Inter,system-ui,sans-serif' font-size='18'>No Kronos balance history yet.</text>
</svg>"""

    series = _downsample_history(history)
    balances = [float(row.get("balance", 0) or 0) for row in series]
    if not balances:
        balances = [0.0]

    width, height = 1200, 340
    pad_l, pad_r, pad_t, pad_b = 72, 36, 54, 70
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    min_v = min(balances)
    max_v = max(balances)
    if max_v == min_v:
        max_v += 1.0
    margin = max((max_v - min_v) * 0.08, 1.0)
    min_v -= margin
    max_v += margin

    def x_at(i: int) -> float:
        return pad_l + (plot_w * i / max(1, len(balances) - 1))

    def y_at(v: float) -> float:
        return pad_t + ((max_v - v) / (max_v - min_v)) * plot_h

    pts = [(x_at(i), y_at(v)) for i, v in enumerate(balances)]
    path = [f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"]
    for x, y in pts[1:]:
        path.append(f"L{x:.2f},{y:.2f}")
    line_path = " ".join(path)
    area_path = f"M{pts[0][0]:.2f},{height-pad_b:.2f} " + " ".join(path) + f" L{pts[-1][0]:.2f},{height-pad_b:.2f} Z"

    first = balances[0]
    last = balances[-1]
    total_change = last - first
    total_change_pct = (total_change / first * 100.0) if first else 0.0
    latest_ts = str(series[-1].get("timestamp", ""))[:19].replace("T", " ")
    start_ts = str(series[0].get("timestamp", ""))[:19].replace("T", " ")

    grid_lines = []
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + frac * plot_h
        val = max_v - frac * (max_v - min_v)
        grid_lines.append((y, val))

    def fmt_currency(v: float) -> str:
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v):,.2f}"

    svg = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}' role='img' aria-label='Kronos full-history PnL graph'>",
        "<defs>",
        "<linearGradient id='bg' x1='0' y1='0' x2='0' y2='1'>",
        "<stop offset='0%' stop-color='#0a1220'/>",
        "<stop offset='100%' stop-color='#050a12'/>",
        "</linearGradient>",
        "<linearGradient id='area' x1='0' y1='0' x2='0' y2='1'>",
        "<stop offset='0%' stop-color='#38bdf8' stop-opacity='0.34'/>",
        "<stop offset='100%' stop-color='#38bdf8' stop-opacity='0.04'/>",
        "</linearGradient>",
        "<filter id='glow' x='-15%' y='-15%' width='130%' height='130%'>",
        "<feGaussianBlur stdDeviation='2.8' result='blur'/>",
        "<feMerge><feMergeNode in='blur'/><feMergeNode in='SourceGraphic'/></feMerge>",
        "</filter>",
        "<style>",
        ".title{font:700 26px Inter,system-ui,sans-serif;fill:#e5eefc}",
        ".sub{font:500 13px Inter,system-ui,sans-serif;fill:#8ea0bf}",
        ".tick{font:12px Inter,system-ui,sans-serif;fill:#8aa0c4}",
        ".grid{stroke:#22314a;stroke-width:1;shape-rendering:crispEdges}",
        ".stat{font:600 13px Inter,system-ui,sans-serif;fill:#bfd0ea}",
        "</style>",
        "</defs>",
        "<rect width='100%' height='100%' fill='url(#bg)' rx='20'/>",
        "<text x='72' y='34' class='title'>Kronos full-history PnL</text>",
        f"<text x='72' y='56' class='sub'>{escape(start_ts)} → {escape(latest_ts)} · {len(series)} settled points</text>",
    ]

    for y, val in grid_lines:
        svg.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{width-pad_r}' y2='{y:.1f}' class='grid' opacity='0.7'/>")
        svg.append(f"<text x='{pad_l-10}' y='{y+4:.1f}' text-anchor='end' class='tick'>${val:,.2f}</text>")

    x_marks = [0, len(series) // 2, len(series) - 1]
    for idx in x_marks:
        x, _ = pts[idx]
        ts = str(series[idx].get('timestamp', ''))[:16].replace('T', ' ')
        svg.append(f"<line x1='{x:.1f}' y1='{pad_t}' x2='{x:.1f}' y2='{height-pad_b}' class='grid' opacity='0.25' stroke-dasharray='4 6'/>")
        svg.append(f"<text x='{x:.1f}' y='{height-26}' text-anchor='middle' class='tick'>{escape(ts)}</text>")

    svg.extend([
        f"<path d='{area_path}' fill='url(#area)'/>",
        f"<path d='{line_path}' fill='none' stroke='#38bdf8' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round' filter='url(#glow)'/>",
        f"<circle cx='{pts[0][0]:.2f}' cy='{pts[0][1]:.2f}' r='5' fill='#93c5fd' stroke='#050a12' stroke-width='2'/>",
        f"<circle cx='{pts[-1][0]:.2f}' cy='{pts[-1][1]:.2f}' r='5' fill='#93c5fd' stroke='#050a12' stroke-width='2'/>",
        f"<text x='{72}' y='{height-38}' class='stat'>Start {fmt_currency(first)}</text>",
        f"<text x='{292}' y='{height-38}' class='stat'>Latest {fmt_currency(last)}</text>",
        f"<text x='{540}' y='{height-38}' class='stat'>Total {fmt_currency(total_change)} ({total_change_pct:+.2f}%)</text>",
    ])

    svg.append("</svg>")
    return "".join(svg)


@app.get("/api/balance_history")
async def get_balance_history():
    """Return full balance/equity history for PnL chart."""
    if not _betting_engine:
        return {"history": []}

    history = _betting_engine.balance_history
    if not history:
        return {"history": []}

    return {"history": history}


@app.get("/api/pnl_svg")
async def get_pnl_svg():
    """Render the full-history Kronos PnL graph as SVG."""
    if not _betting_engine:
        return Response(content=_build_pnl_svg([]), media_type="image/svg+xml")

    return Response(
        content=_build_pnl_svg(_betting_engine.balance_history),
        media_type="image/svg+xml",
    )


@app.get("/api/noble/missions")
async def get_noble_missions():
    """Noble HQ mission feed — derive from bot state."""
    stats = {}
    if _betting_engine:
        stats = _betting_engine.get_stats()

    total_trades = stats.get("total_trades", 0)
    progress = min(total_trades * 2, 100)

    mission = {
        "id": 1,
        "title": "Kronos BTC 5m",
        "priority": "high",
        "status": "active",
        "progress": progress,
        "assignedTo": ["Jorge-052", "Emile-A239"],
        "startedAt": "2026-05-21T08:00:00Z",
    }
    return [mission]


@app.get("/api/noble/ops-feed")
async def get_noble_ops_feed():
    """Noble HQ ops feed — last 20 trades formatted as OpsEvents."""
    events = []
    if not _betting_engine:
        return events

    trades = _betting_engine.get_recent_trades(20)
    for trade in trades:
        events.append({
            "id": trade.get("id"),
            "timestamp": trade.get("timestamp"),
            "member": "Kronos",
            "memberCallSign": "BOT",
            "action": str(trade.get("direction", "")).upper(),
            "type": "mission",
            "details": f"Trade #{trade.get('id')} — {str(trade.get('result', '')).upper()} PnL ${trade.get('pnl')}",
        })
    return events


@app.get("/api/noble/metrics")
async def get_noble_metrics():
    """Noble HQ operational metrics."""
    stats = {}
    if _betting_engine:
        stats = _betting_engine.get_stats()

    return {
        "active_sessions": 1,
        "tokens_today": 0,
        "ops_completed": stats.get("total_trades", 0),
        "uptime": "N/A",
        "cron_jobs": 2,
        "bg_processes": 2,
    }


# ---------------------------------------------------------------------------
# Playwright Browser Observability Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/observability/screenshot")
async def take_screenshot(url: str = "http://localhost:8500", full_page: bool = True):
    """Capture a screenshot of the dashboard or any URL via Playwright."""
    try:
        from playwright_observability import NobleObservability
        obs = await NobleObservability().start(headless=True)
        try:
            path = await obs.screenshot_dashboard(url)
            return {"status": "ok", "screenshot_path": path, "url": url}
        finally:
            await obs.stop()
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/observability/inspect")
async def inspect_page(url: str = "http://localhost:8500"):
    """Inspect page structure and key metrics via Playwright."""
    try:
        from playwright_observability import NobleObservability
        obs = await NobleObservability().start(headless=True)
        try:
            metrics = await obs.inspect_page(url)
            return {"status": "ok", "metrics": metrics, "url": url}
        finally:
            await obs.stop()
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/observability/operator/{operator_id}")
async def capture_operator(operator_id: str, url: str = "http://localhost:8500"):
    """Capture a screenshot of a specific operator profile page."""
    try:
        from playwright_observability import NobleObservability
        obs = await NobleObservability().start(headless=True)
        try:
            path = await obs.capture_operator_view(operator_id, url)
            return {"status": "ok", "screenshot_path": path, "operator_id": operator_id, "url": url}
        finally:
            await obs.stop()
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/screenshots/latest")
async def get_latest_screenshots():
    """List available screenshots taken by Playwright."""
    import glob
    screenshot_dir = "/workspace/noble-hq/public/screenshots"
    files = sorted(glob.glob(os.path.join(screenshot_dir, "*.png")), key=os.path.getmtime, reverse=True)
    screenshots = []
    for f in files[:10]:
        screenshots.append({
            "filename": os.path.basename(f),
            "path": f,
            "url_path": f"/screenshots/{os.path.basename(f)}",
            "size": os.path.getsize(f),
            "created": datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc).isoformat(),
        })
    return {"screenshots": screenshots, "count": len(screenshots)}


# ---------------------------------------------------------------------------
# Static file serving for Noble HQ SPA
# ---------------------------------------------------------------------------
NOBLE_HQ_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "noble-hq", "dist"))

if os.path.isdir(NOBLE_HQ_DIST):
    # Mount assets directory
    assets_dir = os.path.join(NOBLE_HQ_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    
    # Mount screenshots directory for observability
    screenshot_dir = "/workspace/noble-hq/public/screenshots"
    if os.path.isdir(screenshot_dir):
        app.mount("/screenshots", StaticFiles(directory=screenshot_dir), name="screenshots")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve SPA — fallback to index.html for client-side routing."""
        # API routes are handled above — this catches everything else
        file_path = os.path.join(NOBLE_HQ_DIST, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(NOBLE_HQ_DIST, "index.html"))
