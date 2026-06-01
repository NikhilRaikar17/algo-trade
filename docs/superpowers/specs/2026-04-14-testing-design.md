# Testing Design — NiceGUI Algotrading App

**Date:** 2026-04-14  
**Motivation:** Refactoring safety net + behavioral documentation for pure-logic modules.  
**Scope:** `nicegui_app/` — strategy logic, state/cache, data transforms, chart builders, config utilities. UI pages are out of scope.

---

## Test Stack

- **pytest** — test runner
- **pytest-asyncio** — for any async functions
- **pytest-mock** — `mocker` fixture for clean patching

Added to `nicegui_app/pyproject.toml` under `[dependency-groups] dev`.

---

## Directory Structure

```
nicegui_app/
  tests/
    __init__.py
    conftest.py                  # shared fixtures
    test_algo_strategies.py
    test_state.py
    test_data.py
    test_charts.py
    test_config.py
```

---

## Shared Fixtures (`conftest.py`)

| Fixture | Purpose |
|---------|---------|
| `sample_ohlcv_df` | Synthetic 30-row OHLCV DataFrame with IST timestamps; includes a valid ABCD bullish swing sequence |
| `mock_dhan` | `MagicMock` replacing the `dhan` client; canned returns for `expiry_list`, `intraday_minute_data`, `option_chain` |
| `freeze_ist` | Patches `now_ist()` in the target module's namespace to return a fixed IST datetime |

Individual tests receive fixtures and mutate copies — never the shared fixture directly.

---

## Test Coverage Per File

### `test_algo_strategies.py`

| Test | What it documents |
|------|-------------------|
| `test_find_swing_points_highs_and_lows` | Correct high/low swing indices returned for a known OHLCV sequence |
| `test_detect_abcd_bullish_pattern` | Bullish pattern detected when BC/AB ∈ [0.618−tol, 0.786+tol] and CD/AB ∈ [1.0−tol, 1.618+tol] |
| `test_detect_abcd_bearish_pattern` | Bearish pattern detected on high→low→high→low swing sequence |
| `test_detect_abcd_no_pattern_out_of_ratio` | No pattern when ratios fall outside tolerance (parametrized: just-outside, far-outside) |
| `test_detect_rsi_sma_buy_signal` | BUY signal when fast SMA crosses above slow SMA and RSI > 30 |
| `test_detect_rsi_sma_sell_signal` | SELL signal on reverse cross with RSI < 70 |
| `test_detect_rsi_sma_no_signal_rsi_out_of_range` | No signal when RSI condition not met despite SMA cross |
| `test_detect_rsi_only_buy_signal` | BUY when RSI crosses back above 30 from below |
| `test_detect_rsi_only_sell_signal` | SELL when RSI crosses back below 70 from above |
| `test_detect_rsi_only_no_duplicate` | Same signal not emitted twice on consecutive bars |

`_send_telegram` and `save_completed_trade` patched in all `classify_trades` tests.

---

### `test_state.py`

| Test | What it documents |
|------|-------------------|
| `test_cache_miss_returns_none` | `_cache_get` returns `None` for unknown key |
| `test_cache_hit_returns_value` | `_cache_get` returns value after `_cache_set` |
| `test_cache_expires_after_ttl` | Value not returned after TTL elapses (time mocked) |
| `test_dedup_false_before_mark` | `_is_already_sent` returns `False` before `_mark_sent` |
| `test_dedup_true_after_mark` | `_is_already_sent` returns `True` after `_mark_sent` |
| `test_is_market_open_during_hours` | Returns `True` at 10:00 IST on a weekday non-holiday |
| `test_is_market_open_before_open` | Returns `False` at 9:00 IST |
| `test_is_market_open_after_close` | Returns `False` at 15:31 IST |
| `test_is_market_open_on_weekend` | Returns `False` on Saturday |
| `test_is_market_open_on_nse_holiday` | Returns `False` on a known NSE holiday |

File I/O for dedup (`_DEDUP_FILE`) mocked via `mocker.patch("builtins.open")` + `mock_open`.

---

### `test_data.py`

| Test | What it documents |
|------|-------------------|
| `test_get_expiries_parses_response` | Returns correct list from canned `expiry_list` response |
| `test_get_expiries_raises_on_error` | Raises `RuntimeError` when API status is not `"success"` |
| `test_get_expiries_uses_cache` | Second call returns cached value; mock called only once |
| `test_check_dhan_api_ok` | Returns `{"ok": True}` on success response |
| `test_check_dhan_api_error` | Returns `{"ok": False, "error": ...}` on failure |

All Dhan API calls replaced by `mock_dhan` fixture.

---

### `test_charts.py`

| Test | What it documents |
|------|-------------------|
| `test_chart_returns_plotly_structure` | Figure dict has `"data"` and `"layout"` keys |
| `test_chart_floats_are_native_python` | No `numpy.float64` values anywhere in figure dict (guards orjson serialization) |

The float check recurses into nested dicts/lists using a helper that asserts `type(v) is float` (not `isinstance`, which would pass `numpy.float64`).

---

### `test_config.py`

| Test | What it documents |
|------|-------------------|
| `test_is_nse_holiday_true` | Returns `True` for dates in `NSE_HOLIDAYS` set (parametrized sample) |
| `test_is_nse_holiday_false` | Returns `False` for a normal trading day |
| `test_is_trading_day_false_saturday` | Returns `False` for Saturday |
| `test_is_trading_day_false_sunday` | Returns `False` for Sunday |
| `test_is_trading_day_true_weekday` | Returns `True` for Monday non-holiday |

---

## Patching Conventions

- Always patch in the **target module's namespace**, not the source:
  - `mocker.patch("state.now_ist", ...)` not `mocker.patch("config.now_ist", ...)`
  - `mocker.patch("data.dhan", mock_dhan)`
- Use `@pytest.mark.parametrize` for boundary values (ratios, RSI thresholds)
- Use `@pytest.mark.asyncio` for any async functions tested in future

---

## Out of Scope

- UI pages (`nicegui_app/pages/`) — require a running NiceGUI server
- Live Dhan API calls
- Telegram HTTP calls
- End-to-end / integration tests
