"""
Binance Data Client
Connects to Binance WebSocket for BTC/USDT 5m klines and
fetches historical klines via REST API.
Maintains a rolling candle buffer (last 500 candles).
"""

import asyncio
import json
import time
from collections import deque
from datetime import datetime
from typing import Optional, Callable

import pandas as pd
import aiohttp
import websockets


class BinanceClient:
    """
    Fetches and maintains a rolling buffer of BTC/USDT 5-minute klines.

    Uses:
    - REST: https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=500
    - WebSocket: wss://stream.binance.com:9443/ws/btcusdt@kline_5m
    """

    COLUMNS = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore",
    ]

    def __init__(self, symbol: str = "BTCUSDT", max_candles: int = 500):
        self.symbol = symbol
        self.max_candles = max_candles
        self._candles: deque = deque(maxlen=max_candles)
        self._ws = None
        self._running = False
        self._on_candle: Optional[Callable] = None

    async def fetch_historical(self) -> pd.DataFrame:
        """Fetch historical 5m klines from Binance REST API."""
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={self.symbol}&interval=5m&limit={self.max_candles}"
        )
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Binance] Fetching {self.max_candles} historical candles ...")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        if not isinstance(data, list) or len(data) == 0:
            raise RuntimeError(f"Binance REST returned unexpected data: {data}")

        df = pd.DataFrame(data, columns=self.COLUMNS)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)

        # Populate deque
        self._candles.clear()
        for _, row in df.iterrows():
            self._candles.append(row.to_dict())

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Binance] Loaded {len(df)} historical candles "
              f"(from {df['open_time'].iloc[0]} to {df['open_time'].iloc[-1]})")
        return df

    def get_recent_candles(self, n: Optional[int] = None) -> pd.DataFrame:
        """Return last N candles as a DataFrame."""
        candles = list(self._candles)
        if n is not None:
            candles = candles[-n:]

        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        # Normalize columns for Kronos
        df_out = pd.DataFrame()
        df_out["timestamps"] = pd.to_datetime(df["open_time"])
        df_out["open"] = df["open"].astype(float)
        df_out["high"] = df["high"].astype(float)
        df_out["low"] = df["low"].astype(float)
        df_out["close"] = df["close"].astype(float)
        df_out["volume"] = df["volume"].astype(float)
        df_out["amount"] = df_out["volume"] * df_out["close"]
        return df_out

    def set_candle_callback(self, callback: Callable) -> None:
        """Register a callback invoked on each new closed candle."""
        self._on_candle = callback

    async def start_websocket(self) -> None:
        """Connect to Binance WebSocket and stream kline updates."""
        url = f"wss://stream.binance.com:9443/ws/{self.symbol.lower()}@kline_5m"
        self._running = True

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Binance] Connecting WebSocket: {url}")

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                    self._ws = ws
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{ts}] [Binance] WebSocket connected, streaming klines ...")

                    async for msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(msg)

            except (websockets.ConnectionClosed, OSError) as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [Binance] WebSocket disconnected: {e}. Reconnecting in 5s ...")
                await asyncio.sleep(5)
            except Exception as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [Binance] WebSocket error: {e}. Reconnecting in 10s ...")
                await asyncio.sleep(10)

    async def _handle_message(self, msg: str) -> None:
        """Parse and process an incoming WebSocket message."""
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return

        kline = data.get("k", {})
        if not kline:
            return

        is_closed = kline.get("x", False)

        # Build candle dict
        candle = {
            "open_time": pd.to_datetime(kline["t"], unit="ms"),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
            "close_time": pd.to_datetime(kline["T"], unit="ms"),
            "quote_volume": float(kline["q"]),
            "trades": int(kline["n"]),
        }

        if is_closed:
            # Update the buffer — if this candle is already in the buffer (same open_time), replace it
            replaced = False
            for i, c in enumerate(self._candles):
                if c["open_time"] == candle["open_time"]:
                    self._candles[i] = candle
                    replaced = True
                    break
            if not replaced:
                self._candles.append(candle)

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{ts}] [Binance] Candle closed: "
                f"{candle['open_time']} O={candle['open']:.2f} H={candle['high']:.2f} "
                f"L={candle['low']:.2f} C={candle['close']:.2f}"
            )

            if self._on_candle:
                df = self.get_recent_candles()
                try:
                    self._on_candle(df)
                except Exception as e:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{ts}] [Binance] Candle callback error: {e}")

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Binance] WebSocket stopped.")

    @property
    def candle_count(self) -> int:
        return len(self._candles)
