"""
Kronos Prediction Service
Loads Kronos-small + tokenizer from HuggingFace.
Provides predict_direction(ohlcv_df) for BTC price direction prediction.
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Tuple, Optional

import numpy as np
import pandas as pd
import torch

# Ensure local model module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import KronosTokenizer, Kronos, KronosPredictor


class KronosService:
    """
    Wraps the Kronos model for BTC 5-minute price direction prediction.

    Loads Kronos-small (24.7M params) + Kronos-Tokenizer-base from HuggingFace.
    Uses CPU inference by default (model is small enough for real-time CPU).
    """

    def __init__(
        self,
        model_name: str = "NeoQuasar/Kronos-small",
        tokenizer_name: str = "NeoQuasar/Kronos-Tokenizer-base",
        device: Optional[str] = None,
        max_context: int = 512,
        lookback: int = 400,
    ):
        self.model_name = model_name
        self.tokenizer_name = tokenizer_name
        self.max_context = max_context
        self.lookback = lookback
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.predictor: Optional[KronosPredictor] = None
        self._loaded = False
        print(f"[KronosService] Device: {self.device}")

    def load(self) -> None:
        """Download and initialize Kronos model and tokenizer from HuggingFace."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [KronosService] Loading tokenizer from {self.tokenizer_name} ...")
        tokenizer = KronosTokenizer.from_pretrained(self.tokenizer_name)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [KronosService] Loading model from {self.model_name} ...")
        model = Kronos.from_pretrained(self.model_name)

        self.predictor = KronosPredictor(
            model=model,
            tokenizer=tokenizer,
            device=self.device,
            max_context=self.max_context,
        )
        self._loaded = True
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [KronosService] Model loaded successfully (device={self.device})")

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def predict_direction(
        self,
        ohlcv_df: pd.DataFrame,
        pred_len: int = 1,
        temperature: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
    ) -> dict:
        """
        Predict BTC price direction for the next candle(s).

        Args:
            ohlcv_df: DataFrame with columns ['open','high','low','close','volume']
                      plus a DatetimeIndex or 'timestamps' column.
                      Must have at least `lookback` rows.
            pred_len: Number of future candles to predict (default 1).
            temperature: Sampling temperature (lower = more deterministic).
            top_p: Nucleus sampling threshold.
            sample_count: Number of samples to average.

        Returns:
            dict with keys:
                - direction: "Up" or "Down"
                - confidence: float 0-1
                - predicted_close: float
                - predicted_change_pct: float
                - prediction_df: DataFrame with predicted OHLCV row
        """
        if not self._loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        if ohlcv_df.shape[0] < self.lookback:
            raise ValueError(
                f"Need at least {self.lookback} candles, got {ohlcv_df.shape[0]}"
            )

        # Ensure required columns
        required = {"open", "high", "low", "close"}
        missing = required - set(ohlcv_df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        df = ohlcv_df.copy()

        # Add volume if missing
        if "volume" not in df.columns:
            df["volume"] = 0.0
        if "amount" not in df.columns:
            df["amount"] = df["volume"] * df["close"]

        # Use last `lookback` candles
        x_df = df.iloc[-self.lookback:]

        # Get timestamps
        if isinstance(df.index, pd.DatetimeIndex):
            x_timestamp = df.index[-self.lookback:]
        elif "timestamps" in df.columns:
            x_timestamp = pd.DatetimeIndex(df["timestamps"].iloc[-self.lookback:])
        else:
            # Generate synthetic timestamps
            now = datetime.utcnow()
            x_timestamp = pd.DatetimeIndex(
                [now - timedelta(minutes=5 * (self.lookback - i)) for i in range(self.lookback)]
            )

        # Generate future timestamp for prediction
        last_ts = x_timestamp[-1]
        if isinstance(last_ts, pd.Timestamp):
            y_timestamp = pd.DatetimeIndex([last_ts + timedelta(minutes=5 * (i + 1)) for i in range(pred_len)])
        else:
            y_timestamp = pd.DatetimeIndex(
                [datetime.utcnow() + timedelta(minutes=5 * (i + 1)) for i in range(pred_len)]
            )

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [KronosService] Running prediction (lookback={self.lookback}, pred_len={pred_len}) ...")

        try:
            pred_df = self.predictor.predict(
                df=x_df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=temperature,
                top_p=top_p,
                sample_count=sample_count,
                verbose=False,
            )
        except Exception as e:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [KronosService] Prediction failed: {e}")
            raise

        last_close = x_df["close"].iloc[-1]
        predicted_close = float(pred_df["close"].iloc[-1])

        change_pct = ((predicted_close - last_close) / last_close) * 100.0
        direction = "Up" if predicted_close > last_close else "Down"

        # Confidence: map the magnitude of predicted change to confidence (0.5-1.0 range)
        # Larger predicted moves = higher confidence, capped between 0.5 and 1.0
        raw_conf = min(abs(change_pct) / 2.0, 0.5) + 0.5
        confidence = round(raw_conf, 4)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{ts}] [KronosService] Prediction: {direction} "
            f"(close: {last_close:.2f} -> {predicted_close:.2f}, "
            f"delta: {change_pct:+.3f}%, conf: {confidence:.3f})"
        )

        return {
            "direction": direction,
            "confidence": confidence,
            "predicted_close": round(predicted_close, 2),
            "predicted_change_pct": round(change_pct, 3),
            "current_close": round(last_close, 2),
            "prediction_df": pred_df,
        }
