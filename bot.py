"""
Kronos BTC Polymarket Prediction Bot
Main loop that orchestrates:
1. Binance WebSocket for 5m klines
2. Kronos model prediction every 5 minutes
3. Polymarket market discovery + pricing
4. Kelly bet sizing + trade journal
5. API server on port 8500
"""

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

# Local imports
from kronos_service import KronosService
from binance_client import BinanceClient
from polymarket_client import PolymarketClient
from betting_engine import BettingEngine
from api_server import app, set_services, update_prediction, update_signal
from supabase_client import upsert_signal, upsert_status, insert_trade

# Ensure local model module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class KronosBot:
    """
    Main bot orchestrator.

    Lifecycle:
    1. Load Kronos model from HuggingFace
    2. Connect Binance WebSocket + fetch historical candles
    3. Connect Polymarket + find current market
    4. Start API server on port 8500
    5. Every 5 minutes: predict -> find market -> calculate bet -> log
    """

    def __init__(self):
        self.kronos = KronosService()
        self.binance = BinanceClient()
        self.polymarket = PolymarketClient()
        self.betting = BettingEngine(state_file="/workspace/kronos-bot/trade_state.json")

        self._prediction_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_prediction_time: Optional[datetime] = None

    async def run(self):
        """Main entry point."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] ========================================")
        print(f"[{ts}]   Kronos BTC Bot - Initializing")
        print(f"[{ts}] ========================================")

        self._running = True

        # 1. Load Kronos model
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Step 1/5: Loading Kronos model ...")
        self.kronos.load()

        # 2. Fetch historical Binance data
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Step 2/5: Fetching historical BTC data from Binance ...")
        await self.binance.fetch_historical()

        # 3. Register API services
        set_services(self.kronos, self.binance, self.polymarket, self.betting)

        # 4. Start API server
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Step 3/5: Starting API server on port 8500 ...")
        import uvicorn
        api_config = uvicorn.Config(app, host="0.0.0.0", port=8500, log_level="info")
        api_server = uvicorn.Server(api_config)
        api_task = asyncio.create_task(api_server.serve())

        # 5. Find current Polymarket market
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Step 4/5: Finding current Polymarket market ...")
        await self.polymarket.find_current_market()

        # 6. Start WebSocket connections
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Step 5/5: Starting WebSocket connections ...")
        binance_ws = asyncio.create_task(self.binance.start_websocket())

        # Start Polymarket WS if we have a token
        pm_ws = None
        if self.polymarket.current_market:
            token = self.polymarket.current_market.get("clob_token_ids", [None])[0]
            if token:
                pm_ws = asyncio.create_task(self.polymarket.start_orderbook_stream(token))

        # Allow time for WebSocket to connect
        await asyncio.sleep(3)

        # 7. Start prediction loop
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Starting prediction loop (every 5 minutes) ...")
        self._prediction_task = asyncio.create_task(self._prediction_loop())

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] ========================================")
        print(f"[{ts}] [Bot]   Bot RUNNING. API: http://0.0.0.0:8500")
        print(f"[{ts}] [Bot] ========================================")

        # Wait for shutdown
        try:
            await asyncio.gather(
                api_task,
                binance_ws,
                *([pm_ws] if pm_ws else []),
                self._prediction_task,
            )
        except asyncio.CancelledError:
            pass

    async def _prediction_loop(self):
        """Run prediction + betting cycle every 5 minutes, aligned to market closes."""
        while self._running:
            try:
                # Wait until next 5-minute boundary + a few seconds for candle to close
                now = datetime.now(timezone.utc)
                minutes = now.minute
                seconds = now.second
                # Next 5-minute boundary: round up to next multiple of 5
                next_boundary_min = ((minutes // 5) + 1) * 5
                if next_boundary_min >= 60:
                    next_boundary = now.replace(minute=0, second=5, microsecond=0) + timedelta(hours=1)
                else:
                    next_boundary = now.replace(minute=next_boundary_min, second=5, microsecond=0)

                wait_seconds = (next_boundary - now).total_seconds()
                if wait_seconds < 0:
                    wait_seconds = 300  # fallback: wait 5 min

                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [Bot] Next prediction in {wait_seconds:.0f}s (at {next_boundary.isoformat()})")
                await asyncio.sleep(max(wait_seconds, 1))

                await self._run_prediction_cycle()

            except asyncio.CancelledError:
                break
            except Exception as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [Bot] Prediction loop error: {e}")
                await asyncio.sleep(30)  # retry after delay

    async def _run_prediction_cycle(self):
        """Single prediction + betting cycle."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] --- Prediction Cycle Start ---")

        # Step A: Get latest candles
        candles_df = self.binance.get_recent_candles(400)
        if candles_df.empty or len(candles_df) < 400:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Bot] Not enough candles ({len(candles_df)}), skipping prediction")
            return

        # Step B: Run Kronos prediction
        try:
            prediction = self.kronos.predict_direction(candles_df)
            update_prediction(prediction)
            await upsert_signal({
                "signal": "up" if prediction["direction"] == "Up" else "down",
                "confidence": prediction["confidence"],
                "btc_price": prediction.get("current_close", 0),
                "predicted_price": prediction.get("predicted_close", 0),
            })
        except Exception as e:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Bot] Kronos prediction error: {e}")
            return

        # Step C: Refresh current Polymarket market (don't get stuck on expired market)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Refreshing Polymarket market ...")
        fresh_market = await self.polymarket.find_current_market()
        if fresh_market:
            market = fresh_market
        elif not market:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Bot] No Polymarket market available")
            return

        condition_id = market.get("condition_id", "")
        clob_token_ids = market.get("clob_token_ids", [])

        prices = await self.polymarket.get_market_prices(condition_id, clob_token_ids)
        up_price = prices.get("up_price", 0.50)
        down_price = prices.get("down_price", 0.50)

        # Update market prices in current market dict
        market["up_price"] = up_price
        market["down_price"] = down_price

        # Step D: Calculate Kelly bet
        bet = self.betting.calculate_bet(
            predicted_direction=prediction["direction"],
            confidence=prediction["confidence"],
            market_up_price=up_price,
            market_down_price=down_price,
        )
        update_signal(bet)
        await upsert_signal({
            "signal": "up" if bet["direction"] == "Up" else "down",
            "confidence": prediction["confidence"],
            "btc_price": prediction.get("current_close", 0),
            "predicted_price": prediction.get("predicted_close", 0),
        })

        await self._write_status(prediction, bet, market)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        direction_symbol = "📈" if prediction["direction"] == "Up" else "📉"
        print(
            f"[{ts}] [Bot] {direction_symbol} Prediction: {prediction['direction']} "
            f"(conf={prediction['confidence']:.3f}, "
            f"Δ={prediction['predicted_change_pct']:+.3f}%)"
        )
        print(
            f"[{ts}] [Bot] 🎰 Market: Up={up_price:.3f} Down={down_price:.3f}"
        )

        if bet["should_bet"]:
            print(
                f"[{ts}] [Bot] 💰 Kelly Bet: ${bet['amount']} "
                f"({bet['kelly_fraction']*100:.1f}% of bankroll, "
                f"edge={bet['edge']:.3f})"
            )

            # Build enriched prediction dict for trade logging
            trade_prediction = {
                **prediction,
                "market": market.get("question", market.get("slug", "BTC 5m")),
            }

            # Execute dry-run trade
            if bet["direction"] == "Up":
                odds = 1.0 / up_price if up_price > 0 else 1.0
            else:
                odds = 1.0 / down_price if down_price > 0 else 1.0

            self.betting.execute_trade(
                direction=bet["direction"],
                amount=bet["amount"],
                market_odds=odds,
                prediction=trade_prediction,
            )
            db_id = await insert_trade({
                "direction": bet["direction"].lower(),
                "amount": bet["amount"],
                "odds": odds,
                "result": "pending",
                "pnl": 0,
                "market": market.get("question", market.get("slug", "BTC 5m")),
            })
            if db_id is not None and self.betting.current_position:
                self.betting.trades_db_ids[self.betting.current_position["id"]] = db_id
                self.betting._save_state()

            # Auto-settle after market resolution (in real bot, this would wait)
            # For now, we simulate settlement: settle the PREVIOUS trade
            await self._settle_previous_trade(candles_df)
        else:
            print(f"[{ts}] [Bot] ⏸️  No bet: {bet['reason']}")
            # Still try to settle previous trade
            await self._settle_previous_trade(candles_df)

        self._last_prediction_time = datetime.now(timezone.utc)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] --- Prediction Cycle End ---")

    async def _write_status(self, prediction, bet, market):
        try:
            up_price = market.get("up_price", 0.5)
            down_price = market.get("down_price", 0.5)
            stats = self.betting.get_stats()
            await upsert_status({
                "online": True,
                "market": market.get("question", market.get("slug", "")),
                "prediction": "up" if prediction["direction"] == "Up" else "down",
                "confidence": prediction["confidence"],
                "odds_up": up_price,
                "odds_down": down_price,
                "recommended_bet": bet.get("amount") if bet.get("should_bet") else None,
                "recommended_direction": bet["direction"].lower() if bet.get("should_bet") else None,
                "balance": stats.get("balance", 100.0),
            })
        except Exception as e:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Bot] Supabase status write error: {e}")

    async def _settle_previous_trade(self, candles_df):
        """
        Settle older open trades by checking if price moved in predicted direction.
        Only settle trades that are NOT the current position.
        Updates both local state AND Supabase.
        """
        from supabase_client import update_trade_result

        # Find older open trades (not current position)
        if not self.betting.trades:
            return

        open_trades = [t for t in self.betting.trades if t["status"] == "open"]
        if not open_trades:
            return

        # Exclude current position if it exists
        current_id = None
        if self.betting.current_position:
            current_id = self.betting.current_position.get("id")

        trades_to_settle = [t for t in open_trades if t["id"] != current_id]
        if not trades_to_settle:
            return

        if len(candles_df) < 2:
            return

        prev_close = float(candles_df["close"].iloc[-2])
        curr_close = float(candles_df["close"].iloc[-1])
        actual_move_up = curr_close > prev_close

        for trade in trades_to_settle:
            predicted_up = trade["direction"] == "Up"
            won = actual_move_up == predicted_up

            # Local settlement
            payout = trade["amount"] * trade["odds"] if won else 0
            pnl = payout - trade["amount"]
            self.betting.balance += payout
            trade["status"] = "settled"
            trade["result"] = "win" if won else "loss"
            trade["pnl"] = round(pnl, 2)
            trade["balance_after"] = round(self.betting.balance, 2)
            self.betting.balance_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "balance": round(self.betting.balance, 2),
                "trade_id": trade["id"],
                "pnl": round(pnl, 2),
            })
            self.betting._save_state()

            # Supabase settlement
            db_id = self.betting.trades_db_ids.get(trade["id"])
            if db_id:
                await update_trade_result(db_id, trade["result"], pnl)
                print(f"[Bot] Trade #{trade['id']} settled: {trade['result']} PnL=${pnl:+.2f} (Supabase ID: {db_id})")
            else:
                print(f"[Bot] Trade #{trade['id']} settled: {trade['result']} PnL=${pnl:+.2f} (no DB id)")

    async def shutdown(self):
        """Graceful shutdown."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Shutting down ...")
        self._running = False

        if self._prediction_task:
            self._prediction_task.cancel()

        await self.binance.stop()
        await self.polymarket.stop()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Shutdown complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    bot = KronosBot()

    # Handle graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()

    def _shutdown():
        asyncio.create_task(bot.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            # Signal handlers not supported on all platforms
            pass

    try:
        await bot.run()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Bot] Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
