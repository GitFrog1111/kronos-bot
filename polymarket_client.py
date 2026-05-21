"""
Polymarket Client
REST methods for market discovery and pricing.
WebSocket client for real-time orderbook updates on BTC 5m markets.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, List

import aiohttp
import websockets


# Known BTC 5-minute market event slug prefix and condition ID patterns
BTC_5M_SLUG_PREFIX = "btc-updown-5m-"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/"

# Example market info (fallback)
EXAMPLE_CONDITION_ID = "0x064b1bb9c99558d2b2b51458ee13b8d2a7ea94706b080e221ac5f7fd56dd1706"
EXAMPLE_UP_TOKEN = "43966590240594714506536466039235380111688145405199922583976630227813162441943"


class PolymarketClient:
    """
    Client for discovering and tracking Polymarket BTC 5-minute binary markets.

    Provides:
    - find_current_market(): Find the active BTC Up/Down 5m market
    - get_market_prices(): Get current bid/ask/midpoint
    - WebSocket subscription for real-time orderbook updates
    """

    def __init__(self):
        self._current_market: Optional[dict] = None
        self._ws_running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._price_callback: Optional[Callable] = None
        self._orderbook: dict = {"bids": [], "asks": []}
        self._up_midpoint: Optional[float] = None

    # ------------------------------------------------------------------
    # REST Methods
    # ------------------------------------------------------------------

    async def find_current_market(self) -> Optional[dict]:
        """
        Find the current (or next) BTC 5-minute Up/Down market.

        BTC 5m markets use slug format: btc-updown-5m-{UNIX_TIMESTAMP}
        where the timestamp is the 5-minute aligned market start time.

        Returns dict with keys: condition_id, clob_token_ids, question,
        start_time, end_time, slug, up_price, down_price
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Polymarket] Searching for current BTC 5m market ...")

        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())

        # Try the current and next 5-minute boundary timestamps
        # Round to 5-minute boundaries
        current_boundary = (now_ts // 300) * 300  # Current 5-min boundary
        candidate_timestamps = [current_boundary, current_boundary + 300]

        for ts_candidate in candidate_timestamps:
            slug = f"btc-updown-5m-{ts_candidate}"
            try:
                async with aiohttp.ClientSession() as session:
                    # Try events endpoint with this specific slug
                    events_url = f"{GAMMA_API_BASE}/events?slug={slug}"
                    async with session.get(events_url) as resp:
                        if resp.status == 200:
                            events = await resp.json()
                            if events and len(events) > 0:
                                event = events[0] if isinstance(events, list) else events
                                markets = event.get("markets", [])
                                if markets:
                                    print(f"[{ts}] [Polymarket] Found market via slug: {slug}")
                                    return await self._enrich_market(markets[0])
            except Exception as e:
                print(f"[{ts}] [Polymarket] Slug {slug} error: {e}")
                continue

        # Try searching the Gamma API broadly
        try:
            async with aiohttp.ClientSession() as session:
                search_url = f"{GAMMA_API_BASE}/public-search?q=btc-updown-5m"
                async with session.get(search_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        events = data.get("events", [])
                        for event in events:
                            slug = event.get("slug", "")
                            title = event.get("title", "")
                            # Only match the timestamped BTC 5m markets
                            if "btc-updown-5m" in slug and event.get("active"):
                                markets = event.get("markets", [])
                                if markets:
                                    print(f"[{ts}] [Polymarket] Found market via search: {slug}")
                                    # Find the market closest to now
                                    best = markets[0]
                                    for m in markets:
                                        start = m.get("startDate", m.get("start_date", ""))
                                        if start:
                                            try:
                                                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                                                diff = abs((now - start_dt).total_seconds())
                                                if diff < 600:
                                                    best = m
                                                    break
                                            except (ValueError, TypeError):
                                                pass
                                    return await self._enrich_market(best)
        except Exception as e:
            print(f"[{ts}] [Polymarket] Search error: {e}")

        # Try broad Gamma API events search with Bitcoin tag
        try:
            async with aiohttp.ClientSession() as session:
                broad_url = f"{GAMMA_API_BASE}/events?active=true&archived=false&closed=false&tag=Bitcoin"
                async with session.get(broad_url) as resp:
                    if resp.status == 200:
                        events = await resp.json()
                        for event in events:
                            title = (event.get("title", "") + " " + event.get("slug", "")).lower()
                            if "up or down" in title or "updown" in title or "bitcoin up" in title:
                                markets = event.get("markets", [])
                                if markets:
                                    # Pick the market closest to now by startDate
                                    best = markets[0]
                                    for m in markets:
                                        start = m.get("startDate", m.get("start_date", ""))
                                        if start:
                                            try:
                                                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                                                diff = abs((now - start_dt).total_seconds())
                                                if diff < 600:
                                                    best = m
                                                    break
                                            except (ValueError, TypeError):
                                                pass
                                    print(f"[{ts}] [Polymarket] Found market via broad tag search: {best.get('slug', '')}")
                                    return await self._enrich_market(best)
        except Exception as e:
            print(f"[{ts}] [Polymarket] Broad tag search error: {e}")

        # Use the fallback with generated slug for current boundary
        fallback_slug = f"btc-updown-5m-{current_boundary}"
        print(f"[{ts}] [Polymarket] Using fallback market (slug: {fallback_slug})")
        return self._build_fallback_market(fallback_slug)

    async def _enrich_market(self, market: dict) -> dict:
        """Fetch full market details including token IDs and orderbook."""
        slug = market.get("slug", "")
        condition_id = market.get("conditionId", market.get("condition_id", ""))

        # Get clobTokenIds from the market's tokens
        clob_token_ids = []
        tokens = market.get("clobTokenIds", market.get("tokens", []))
        if tokens:
            if isinstance(tokens[0], dict):
                clob_token_ids = [t.get("tokenId", t.get("token_id", "")) for t in tokens]
            else:
                clob_token_ids = tokens

        if not clob_token_ids:
            clob_token_ids = self._parse_token_ids_from_market(market)

        # Extract outcomePrices from Gamma API response (list of strings like ["0.505", "0.495"])
        outcome_prices = market.get("outcomePrices", [])
        up_price = 0.50
        down_price = 0.50
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                up_price = round(float(outcome_prices[0]), 4)
                down_price = round(float(outcome_prices[1]), 4)
            except (ValueError, TypeError):
                pass

        result = {
            "slug": slug,
            "condition_id": condition_id,
            "clob_token_ids": clob_token_ids,
            "question": market.get("question", market.get("title", "BTC Up/Down 5m")),
            "start_time": market.get("startTime", market.get("start_time", "")),
            "end_time": market.get("endTime", market.get("end_time", "")),
            "up_price": up_price,
            "down_price": down_price,
        }

        # Only fall back to CLOB orderbook when outcomePrices is missing
        if (up_price == 0.50 and down_price == 0.50) and condition_id and clob_token_ids:
            prices = await self.get_market_prices(condition_id, clob_token_ids)
            result.update(prices)

        self._current_market = result
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Polymarket] Market found: {result['question']} "
              f"(Up={result['up_price']:.3f}, Down={result['down_price']:.3f})")
        return result

    async def get_market_prices(
        self, condition_id: str, clob_token_ids: List[str]
    ) -> dict:
        """
        Get current bid/ask/midpoint prices for a market.

        Args:
            condition_id: The Polymarket condition ID.
            clob_token_ids: List of CLOB token IDs [up_token, down_token].

        Returns:
            dict with up_price, down_price, up_bid, up_ask, down_bid, down_ask
        """
        if not clob_token_ids or len(clob_token_ids) < 2:
            # Try to fetch orderbook for just the first token
            up_token = clob_token_ids[0] if clob_token_ids else EXAMPLE_UP_TOKEN
        else:
            up_token = clob_token_ids[0]
            # down_token = clob_token_ids[1]

        try:
            # Get orderbook for the UP token
            book_url = f"{CLOB_API_BASE}/book?token_id={up_token}"
            async with aiohttp.ClientSession() as session:
                async with session.get(book_url) as resp:
                    if resp.status != 200:
                        return {"up_price": 0.50, "down_price": 0.50}
                    book = await resp.json()

            bids = book.get("bids", [])
            asks = book.get("asks", [])

            best_bid = self._normalize_price(bids[0]["price"]) if bids else 0.0
            best_ask = self._normalize_price(asks[0]["price"]) if asks else 1.0

            if best_bid and best_ask:
                up_mid = (best_bid + best_ask) / 2
            elif best_bid:
                up_mid = best_bid
            elif best_ask:
                up_mid = best_ask
            else:
                up_mid = 0.50

            up_mid = round(up_mid, 4)
            down_mid = round(1.0 - up_mid, 4)

            self._up_midpoint = up_mid

            return {
                "up_price": up_mid,
                "down_price": down_mid,
                "up_bid": round(best_bid, 4),
                "up_ask": round(best_ask, 4),
            }
        except Exception as e:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Polymarket] Error fetching prices: {e}")
            return {"up_price": 0.50, "down_price": 0.50}

    def _parse_token_ids_from_market(self, market: dict) -> List[str]:
        """Attempt to extract token IDs from various market data formats."""
        # clobTokenIds is the canonical source — array of hex strings like
        # ["0xabc...", "0xdef..."] or decimal strings. Use it directly.
        clob_ids = market.get("clobTokenIds", [])
        if clob_ids and isinstance(clob_ids, list):
            return [str(t) for t in clob_ids]

        # Fallback: try outcomes (which may be dicts in some API versions)
        outcomes = market.get("outcomes", [])
        token_ids = []
        for o in outcomes:
            if isinstance(o, dict):
                tid = o.get("tokenId", o.get("token_id", o.get("id", "")))
                if tid:
                    token_ids.append(str(tid))
        return token_ids

    @staticmethod
    def _normalize_price(price) -> float:
        """Normalize CLOB price: integers (cents) -> divide by 100, decimals kept as-is."""
        p = float(price)
        if p > 1.0:
            return p / 100.0
        return p

    def _build_fallback_market(self, slug: str = "btc-updown-5m") -> dict:
        """Build a fallback market with known example data."""
        return {
            "slug": slug,
            "condition_id": EXAMPLE_CONDITION_ID,
            "clob_token_ids": [EXAMPLE_UP_TOKEN, ""],
            "question": "Bitcoin Up or Down? (5m)",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "up_price": 0.50,
            "down_price": 0.50,
            "is_fallback": True,
        }

    # ------------------------------------------------------------------
    # WebSocket Methods
    # ------------------------------------------------------------------

    def set_price_callback(self, callback: Callable) -> None:
        """Register a callback invoked with updated price data."""
        self._price_callback = callback

    async def start_orderbook_stream(self, token_id: Optional[str] = None) -> None:
        """
        Connect to CLOB WebSocket and subscribe to orderbook for the given token.
        """
        tid = token_id or EXAMPLE_UP_TOKEN
        self._ws_running = True

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Polymarket] Connecting WebSocket: {CLOB_WS_URL}")

        while self._ws_running:
            try:
                async with websockets.connect(CLOB_WS_URL, ping_interval=30, ping_timeout=10) as ws:
                    self._ws = ws

                    # Subscribe to book channel
                    sub_msg = {
                        "type": "subscribe",
                        "channel": "book",
                        "asset_id": tid,
                    }
                    await ws.send(json.dumps(sub_msg))

                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{ts}] [Polymarket] Subscribed to orderbook for token={tid[:16]}...")

                    async for msg in ws:
                        if not self._ws_running:
                            break
                        await self._handle_book_message(msg)

            except (websockets.ConnectionClosed, OSError) as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [Polymarket] WS disconnected: {e}. Reconnecting in 5s ...")
                await asyncio.sleep(5)
            except Exception as e:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] [Polymarket] WS error: {e}. Reconnecting in 10s ...")
                await asyncio.sleep(10)

    async def _handle_book_message(self, msg: str) -> None:
        """Parse an orderbook update message."""
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return

        # Update internal orderbook
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if bids or asks:
            self._orderbook = {"bids": bids, "asks": asks}

            best_bid = self._normalize_price(bids[0]["price"]) if bids else 0.0
            best_ask = self._normalize_price(asks[0]["price"]) if asks else 1.0

            if best_bid and best_ask:
                mid = round((best_bid + best_ask) / 2, 4)
            elif best_bid:
                mid = best_bid
            else:
                mid = best_ask

            self._up_midpoint = mid

            if self._price_callback:
                try:
                    self._price_callback({
                        "up_mid": mid,
                        "down_mid": round(1.0 - mid, 4),
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                    })
                except Exception:
                    pass

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._ws_running = False
        if self._ws:
            await self._ws.close()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Polymarket] WebSocket stopped.")

    @property
    def current_market(self) -> Optional[dict]:
        return self._current_market

    @property
    def up_midpoint(self) -> Optional[float]:
        return self._up_midpoint
