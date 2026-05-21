"""
API Server
FastAPI server on port 8500 exposing bot status, trades, performance,
and current signal endpoints. CORS enabled for localhost:5173 and all origins.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
# Static file serving for Noble HQ SPA
# ---------------------------------------------------------------------------
NOBLE_HQ_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "noble-hq", "dist"))

if os.path.isdir(NOBLE_HQ_DIST):
    # Mount assets directory
    assets_dir = os.path.join(NOBLE_HQ_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve SPA — fallback to index.html for client-side routing."""
        # API routes are handled above — this catches everything else
        file_path = os.path.join(NOBLE_HQ_DIST, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(NOBLE_HQ_DIST, "index.html"))
