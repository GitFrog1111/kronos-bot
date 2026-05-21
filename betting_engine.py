"""
Betting Engine
Kelly criterion position sizing with dry-run mode.
Tracks trades, P&L, and balance history.
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional


class BettingEngine:
    """
    Calculates bet sizes using fractional Kelly criterion.
    Operates in dry-run mode with a starting balance of $100.

    Kelly formula:
        f* = edge / (odds - 1)
        edge = predicted_prob - market_prob
        Kelly fraction = 0.35 (conservative)
        Bet size = bankroll * 0.35 * f* (capped at 25% of bankroll)
        Round to nearest $1

    Only bets if confidence > 0.55 (minimal edge threshold).
    """

    def __init__(
        self,
        initial_balance: float = 100.0,
        kelly_fraction: float = 0.35,
        max_bet_pct: float = 0.25,
        min_confidence: float = 0.55,
        state_file: str = "trade_state.json",
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.kelly_fraction = kelly_fraction
        self.max_bet_pct = max_bet_pct
        self.min_confidence = min_confidence
        self.state_file = state_file

        self.trades: List[dict] = []
        self.balance_history: List[dict] = []
        self.trades_db_ids: Dict[int, int] = {}  # local trade id -> Supabase row id
        self.current_position: Optional[dict] = None

        # Load persisted state if available
        self._load_state()

    def calculate_bet(
        self,
        predicted_direction: str,
        confidence: float,
        market_up_price: float,
        market_down_price: float,
    ) -> dict:
        """
        Calculate the Kelly bet for a prediction.

        Args:
            predicted_direction: "Up" or "Down"
            confidence: Model confidence (0-1)
            market_up_price: Current midpoint for Up token (0-1)
            market_down_price: Current midpoint for Down token (0-1)

        Returns:
            dict with: direction, amount, kelly_fraction, edge, market_prob,
                       should_bet, reason
        """
        # Convert confidence to predicted probability
        predicted_prob = confidence

        # Market-implied probability for the predicted direction
        if predicted_direction == "Up":
            market_prob = market_up_price
        else:
            market_prob = market_down_price

        edge = predicted_prob - market_prob

        # Check minimum confidence threshold
        if confidence < self.min_confidence:
            return {
                "direction": predicted_direction,
                "amount": 0,
                "kelly_fraction": 0,
                "edge": round(edge, 4),
                "market_prob": round(market_prob, 4),
                "predicted_prob": round(predicted_prob, 4),
                "should_bet": False,
                "reason": f"Confidence {confidence:.3f} below threshold {self.min_confidence}",
            }

        # Check for edge
        if edge <= 0:
            return {
                "direction": predicted_direction,
                "amount": 0,
                "kelly_fraction": 0,
                "edge": round(edge, 4),
                "market_prob": round(market_prob, 4),
                "predicted_prob": round(predicted_prob, 4),
                "should_bet": False,
                "reason": f"No edge (edge={edge:.4f})",
            }

        # Market odds for the bet direction
        if predicted_direction == "Up":
            odds = 1.0 / market_up_price if market_up_price > 0 else float("inf")
        else:
            odds = 1.0 / market_down_price if market_down_price > 0 else float("inf")

        # Kelly fraction: f* = edge / (odds - 1)
        if odds <= 1:
            return {
                "direction": predicted_direction,
                "amount": 0,
                "kelly_fraction": 0,
                "edge": round(edge, 4),
                "market_prob": round(market_prob, 4),
                "predicted_prob": round(predicted_prob, 4),
                "should_bet": False,
                "reason": f"Invalid odds ({odds:.2f})",
            }

        kelly_f_star = edge / (odds - 1)

        # Apply fractional Kelly
        bet_fraction = kelly_f_star * self.kelly_fraction

        # Cap at max_bet_pct of bankroll
        bet_fraction = min(bet_fraction, self.max_bet_pct)

        # Don't bet negative
        bet_fraction = max(0, bet_fraction)

        bet_amount = round(self.balance * bet_fraction)

        return {
            "direction": predicted_direction,
            "amount": bet_amount,
            "kelly_fraction": round(bet_fraction, 4),
            "edge": round(edge, 4),
            "market_prob": round(market_prob, 4),
            "predicted_prob": round(predicted_prob, 4),
            "should_bet": bet_amount > 0,
            "reason": (
                f"Bet ${bet_amount} ({bet_fraction*100:.1f}% of bankroll)"
                if bet_amount > 0
                else "No bet (zero size)"
            ),
        }

    def execute_trade(
        self,
        direction: str,
        amount: float,
        market_odds: float,
        prediction: dict,
    ) -> dict:
        """
        Record a trade in dry-run mode.

        In a real system this would place an order on Polymarket CLOB.
        Here we just log the trade and update balance for tracking.

        The result is marked as 'pending' initially; call settle_trade()
        when the market resolves.
        """
        if amount <= 0:
            return {"status": "skipped", "reason": "Zero bet amount"}

        # Deduct bet from balance
        self.balance -= amount

        trade = {
            "id": len(self.trades) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market": prediction.get("market", "unknown"),
            "direction": direction,
            "amount": amount,
            "odds": round(market_odds, 4),
            "balance_after": round(self.balance, 2),
            "status": "open",
            "result": None,
            "pnl": None,
            "predicted_close": prediction.get("predicted_close"),
            "predicted_change_pct": prediction.get("predicted_change_pct"),
            "confidence": prediction.get("confidence"),
        }

        self.trades.append(trade)
        self.current_position = trade
        self._save_state()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{ts}] [Betting] EXECUTED: {direction} ${amount:.2f} "
            f"@ {market_odds:.3f} | Balance: ${self.balance:.2f}"
        )

        return {"status": "executed", "trade": trade}

    def settle_trade(self, won: bool) -> Optional[dict]:
        """
        Settle the current open trade.

        Args:
            won: True if the prediction was correct, False otherwise.
        """
        if not self.current_position:
            return None

        trade = self.current_position
        payout = trade["amount"] * trade["odds"] if won else 0
        pnl = payout - trade["amount"]

        self.balance += payout
        trade["status"] = "settled"
        trade["result"] = "win" if won else "loss"
        trade["pnl"] = round(pnl, 2)
        trade["balance_after"] = round(self.balance, 2)

        self.balance_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": round(self.balance, 2),
            "trade_id": trade["id"],
            "pnl": round(pnl, 2),
        })

        self.current_position = None
        self._save_state()

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "WON" if won else "LOST"
        print(
            f"[{ts}] [Betting] SETTLED: {status} "
            f"P&L=${pnl:+.2f} | Balance: ${self.balance:.2f}"
        )

        return trade

    def get_stats(self) -> dict:
        """Return current performance statistics."""
        settled = [t for t in self.trades if t["status"] == "settled"]
        wins = [t for t in settled if t["result"] == "win"]
        losses = [t for t in settled if t["result"] == "loss"]

        total_trades = len(settled)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total_trades if total_trades > 0 else 0

        total_pnl = sum(t.get("pnl", 0) or 0 for t in settled)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        # Sharpe-like: mean(pnl) / std(pnl)
        pnls = [t.get("pnl", 0) or 0 for t in settled]
        if len(pnls) > 1:
            import numpy as np
            pnl_std = float(np.std(pnls))
            sharpe = (float(np.mean(pnls)) / pnl_std) if pnl_std > 0 else 0
        else:
            sharpe = 0

        return {
            "balance": round(self.balance, 2),
            "initial_balance": self.initial_balance,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / self.initial_balance) * 100, 2),
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 2),
            "sharpe": round(sharpe, 4),
            "current_position": self.current_position,
        }

    def get_recent_trades(self, n: int = 20) -> List[dict]:
        """Return the last N trades."""
        return self.trades[-n:]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist trade state to JSON."""
        state = {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "trades": self.trades,
            "balance_history": self.balance_history,
            "current_position": self.current_position,
            "trades_db_ids": self.trades_db_ids,
        }
        try:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Betting] Failed to save state: {e}")

    def _load_state(self) -> None:
        """Load persisted trade state from JSON."""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)

            self.balance = state.get("balance", self.initial_balance)
            self.trades = state.get("trades", [])
            self.balance_history = state.get("balance_history", [])
            self.current_position = state.get("current_position")
            self.trades_db_ids = state.get("trades_db_ids", {})

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{ts}] [Betting] Loaded state: balance=${self.balance:.2f}, "
                f"{len(self.trades)} trades"
            )
        except Exception as e:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [Betting] Failed to load state: {e}")

    def reset(self) -> None:
        """Reset all state to initial values."""
        self.balance = self.initial_balance
        self.trades = []
        self.balance_history = []
        self.current_position = None
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [Betting] State reset.")
