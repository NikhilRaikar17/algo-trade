"""
Plotly chart builders for ABCD patterns and RSI + SMA strategies.
"""

import plotly.graph_objects as go

from config import SMA_FAST, SMA_SLOW, RSI_OVERBOUGHT, RSI_OVERSOLD


def build_candlestick_with_abcd(candles, swings, patterns, contract_name, current_price):
    """Build a Plotly candlestick chart with ABCD pattern overlay."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=candles["timestamp"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )

    if swings:
        swing_highs = [s for s in swings if s["type"] == "high"]
        swing_lows = [s for s in swings if s["type"] == "low"]
        if swing_highs:
            fig.add_trace(
                go.Scatter(
                    x=[s["time"] for s in swing_highs],
                    y=[s["price"] for s in swing_highs],
                    mode="markers",
                    marker=dict(symbol="triangle-down", size=10, color="#ef5350"),
                    name="Swing High",
                )
            )
        if swing_lows:
            fig.add_trace(
                go.Scatter(
                    x=[s["time"] for s in swing_lows],
                    y=[s["price"] for s in swing_lows],
                    mode="markers",
                    marker=dict(symbol="triangle-up", size=10, color="#26a69a"),
                    name="Swing Low",
                )
            )

    colors = ["#ff9800", "#2196f3", "#9c27b0", "#00bcd4", "#e91e63"]
    for idx, p in enumerate(patterns):
        color = colors[idx % len(colors)]
        pts = [p["A"], p["B"], p["C"], p["D"]]
        fig.add_trace(
            go.Scatter(
                x=[pt["time"] for pt in pts],
                y=[pt["price"] for pt in pts],
                mode="lines+markers+text",
                line=dict(color=color, width=2, dash="dot"),
                marker=dict(size=12, color=color),
                text=["A", "B", "C", "D"],
                textposition="top center",
                textfont=dict(size=14, color=color),
                name=f"ABCD {idx+1} ({p['type']})",
            )
        )
        fig.add_hline(
            y=p["target"],
            line_dash="dash",
            line_color="green",
            annotation_text=f"Target {p['target']:.2f}",
            annotation_position="bottom right",
        )
        fig.add_hline(
            y=p["stop_loss"],
            line_dash="dash",
            line_color="red",
            annotation_text=f"SL {p['stop_loss']:.2f}",
            annotation_position="bottom right",
        )

    fig.update_layout(
        height=500,
        xaxis_rangeslider_visible=False,
        xaxis_title="Time",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
    )
    return fig


def build_candlestick_with_rsi_sma(candles, df_ind, signals):
    """Build Plotly candlestick + SMA + RSI charts for RSI+SMA strategy."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=candles["timestamp"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )
    if not df_ind.empty:
        fig.add_trace(
            go.Scatter(
                x=df_ind["timestamp"],
                y=df_ind["sma_fast"],
                mode="lines",
                line=dict(color="#2196f3", width=1.5),
                name=f"SMA {SMA_FAST}",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_ind["timestamp"],
                y=df_ind["sma_slow"],
                mode="lines",
                line=dict(color="#ff9800", width=1.5),
                name=f"SMA {SMA_SLOW}",
            )
        )

    buy_sigs = [s for s in signals if s["type"] == "Bullish"]
    sell_sigs = [s for s in signals if s["type"] == "Bearish"]
    if buy_sigs:
        fig.add_trace(
            go.Scatter(
                x=[s["time"] for s in buy_sigs],
                y=[s["entry"] for s in buy_sigs],
                mode="markers",
                marker=dict(symbol="triangle-up", size=14, color="#26a69a"),
                name="Buy Signal",
            )
        )
    if sell_sigs:
        fig.add_trace(
            go.Scatter(
                x=[s["time"] for s in sell_sigs],
                y=[s["entry"] for s in sell_sigs],
                mode="markers",
                marker=dict(symbol="triangle-down", size=14, color="#ef5350"),
                name="Sell Signal",
            )
        )
    fig.update_layout(
        height=500,
        xaxis_rangeslider_visible=False,
        xaxis_title="Time",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
    )

    fig_rsi = go.Figure()
    if not df_ind.empty:
        fig_rsi.add_trace(
            go.Scatter(
                x=df_ind["timestamp"],
                y=df_ind["rsi"],
                mode="lines",
                line=dict(color="#9c27b0", width=1.5),
                name="RSI",
            )
        )
        fig_rsi.add_hline(
            y=RSI_OVERBOUGHT,
            line_dash="dash",
            line_color="red",
            annotation_text="Overbought (70)",
        )
        fig_rsi.add_hline(
            y=RSI_OVERSOLD,
            line_dash="dash",
            line_color="green",
            annotation_text="Oversold (30)",
        )
        fig_rsi.update_layout(
            height=200,
            yaxis_title="RSI",
            xaxis_title="Time",
            margin=dict(l=0, r=0, t=10, b=0),
        )

    return fig, fig_rsi


def _to_str_timestamps(ts_series):
    """Convert pandas Timestamp series to ISO strings for JSON serialization."""
    return ts_series.dt.strftime("%Y-%m-%d %H:%M:%S").tolist()


def _sig_time_str(s):
    """Convert a signal's time to string."""
    t = s["time"]
    if hasattr(t, "strftime"):
        return t.strftime("%Y-%m-%d %H:%M:%S")
    return str(t)


def build_candlestick_with_rsi_only(candles, df_ind, signals):
    """Build Plotly candlestick + RSI charts for RSI-only strategy."""
    ts = _to_str_timestamps(candles["timestamp"])

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=ts,
            open=candles["open"].tolist(),
            high=candles["high"].tolist(),
            low=candles["low"].tolist(),
            close=candles["close"].tolist(),
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )

    buy_sigs = [s for s in signals if s["type"] == "Bullish"]
    sell_sigs = [s for s in signals if s["type"] == "Bearish"]
    if buy_sigs:
        fig.add_trace(
            go.Scatter(
                x=[_sig_time_str(s) for s in buy_sigs],
                y=[s["entry"] for s in buy_sigs],
                mode="markers",
                marker=dict(symbol="triangle-up", size=14, color="#26a69a"),
                name="Buy (RSI oversold exit)",
            )
        )
    if sell_sigs:
        fig.add_trace(
            go.Scatter(
                x=[_sig_time_str(s) for s in sell_sigs],
                y=[s["entry"] for s in sell_sigs],
                mode="markers",
                marker=dict(symbol="triangle-down", size=14, color="#ef5350"),
                name="Sell (RSI overbought exit)",
            )
        )

    for s in signals:
        fig.add_hline(
            y=s["target"],
            line_dash="dash",
            line_color="green",
            line_width=0.5,
        )
        fig.add_hline(
            y=s["stop_loss"],
            line_dash="dash",
            line_color="red",
            line_width=0.5,
        )

    fig.update_layout(
        height=500,
        xaxis_rangeslider_visible=False,
        xaxis_title="Time",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
    )

    fig_rsi = go.Figure()
    if not df_ind.empty:
        ind_ts = _to_str_timestamps(df_ind["timestamp"])
        fig_rsi.add_trace(
            go.Scatter(
                x=ind_ts,
                y=df_ind["rsi"].tolist(),
                mode="lines",
                line=dict(color="#9c27b0", width=1.5),
                name="RSI",
            )
        )
        fig_rsi.add_hline(
            y=RSI_OVERBOUGHT,
            line_dash="dash",
            line_color="red",
            annotation_text="Overbought (70)",
        )
        fig_rsi.add_hline(
            y=RSI_OVERSOLD,
            line_dash="dash",
            line_color="green",
            annotation_text="Oversold (30)",
        )
        fig_rsi.add_hline(
            y=50,
            line_dash="dot",
            line_color="gray",
            opacity=0.4,
        )
        # Mark signal points on RSI chart
        if buy_sigs:
            fig_rsi.add_trace(
                go.Scatter(
                    x=[_sig_time_str(s) for s in buy_sigs],
                    y=[s["rsi"] for s in buy_sigs],
                    mode="markers",
                    marker=dict(symbol="triangle-up", size=10, color="#26a69a"),
                    name="Buy Signal",
                )
            )
        if sell_sigs:
            fig_rsi.add_trace(
                go.Scatter(
                    x=[_sig_time_str(s) for s in sell_sigs],
                    y=[s["rsi"] for s in sell_sigs],
                    mode="markers",
                    marker=dict(symbol="triangle-down", size=10, color="#ef5350"),
                    name="Sell Signal",
                )
            )
        fig_rsi.update_layout(
            height=250,
            yaxis_title="RSI",
            xaxis_title="Time",
            margin=dict(l=0, r=0, t=10, b=0),
        )

    return fig, fig_rsi
