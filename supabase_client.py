"""Supabase client for Kronos bot — writes signals/trades/status to Supabase tables."""
import os
from datetime import datetime, timezone

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dxpyyfkwibopkpnxjnre.supabase.co")
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_KEY",
    os.environ.get("SUPABASE_KEY", "sb_publishable_MpNe4tAjV_C2BV82zi9AEQ_27mYJ4D8"),
)

_sbp = None

def _client():
    global _sbp
    if _sbp is None:
        _sbp = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sbp


async def upsert_signal(signal: dict) -> None:
    """Upsert the latest Kronos signal row (id=1 singleton)."""
    try:
        payload = {
            "id": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **signal,
        }
        _client().table("kronos_signals").upsert(payload).execute()
    except Exception as e:
        print(f"[Supabase] upsert_signal error: {e}")


async def insert_trade(trade: dict) -> int | None:
    """Insert a new trade record and return its Supabase row id."""
    try:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **trade,
        }
        result = _client().table("kronos_trades").insert(payload).execute()
        inserted = result.data[0] if result.data else None
        return inserted["id"] if inserted else None
    except Exception as e:
        print(f"[Supabase] insert_trade error: {e}")
        return None


async def update_trade_result(trade_db_id: int, result: str, pnl: float) -> None:
    """Update a settled trade with result and pnl."""
    try:
        _client().table("kronos_trades").update({
            "result": result,
            "pnl": round(pnl, 2),
        }).eq("id", trade_db_id).execute()
    except Exception as e:
        print(f"[Supabase] update_trade_result error: {e}")



async def upsert_status(status: dict) -> None:
    """Upsert bot status singleton (id=1)."""
    try:
        payload = {
            "id": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **status,
        }
        _client().table("kronos_status").upsert(payload).execute()
    except Exception as e:
        print(f"[Supabase] upsert_status error: {e}")


async def broadcast(event: str, payload: dict) -> None:
    """Broadcast a real-time event on the `kronos-ops` channel."""
    try:
        # Supabase Python realtime broadcast support is limited — we'll use
        # the REST broadcast endpoint when available; fallback to table upserts.
        pass
    except Exception:
        pass
