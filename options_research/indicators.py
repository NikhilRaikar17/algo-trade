"""Optional TA-Lib wrappers for underlying OHLCV indicators."""
import pandas as pd


def calculate_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with RSI, MACD, SMA20/50 and ATR14 columns."""
    required = {"close", "high", "low"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("missing OHLC columns: " + ", ".join(sorted(missing)))
    try:
        import talib
    except ImportError as exc:
        raise RuntimeError("TA-Lib is optional; install its Python package and native library") from exc
    out = frame.copy()
    close, high, low = out["close"].astype(float), out["high"].astype(float), out["low"].astype(float)
    out["rsi_14"] = talib.RSI(close, timeperiod=14)
    macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd, signal, hist
    out["sma_20"] = talib.SMA(close, timeperiod=20)
    out["sma_50"] = talib.SMA(close, timeperiod=50)
    out["atr_14"] = talib.ATR(high, low, close, timeperiod=14)
    return out
