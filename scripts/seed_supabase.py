"""Seed Supabase tables with current bot state after tables are created."""
import asyncio
import json
import sys

sys.path.insert(0, "/workspace/kronos-bot")
from betting_engine import BettingEngine
from supabase_client import upsert_signal, upsert_status, insert_trade

async def seed():
    be = BettingEngine(state_file="/workspace/kronos-bot/trade_state.json")
    stats = be.get_stats()
    
    # Seed signal with idle state
    await upsert_signal({
        "signal": "none",
        "confidence": 0,
        "btc_price": 0,
        "predicted_price": 0,
    })
    
    # Seed status
    await upsert_status({
        "online": True,
        "market": "BTC 5m",
        "prediction": "none",
        "confidence": 0,
        "odds_up": 0.5,
        "odds_down": 0.5,
        "recommended_bet": None,
        "recommended_direction": None,
        "balance": stats.get("balance", 100.0),
    })
    
    # Seed trades
    for trade in be.get_recent_trades(500):
        await insert_trade({
            "market": trade.get("market", "BTC 5m"),
            "direction": trade.get("direction", "").lower(),
            "amount": trade.get("amount", 0),
            "odds": trade.get("odds", 0),
            "result": trade.get("result") or trade.get("status", "pending"),
            "pnl": trade.get("pnl", 0),
        })
    
    print("Seed complete.")

if __name__ == "__main__":
    asyncio.run(seed())
