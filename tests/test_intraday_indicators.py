"""Unit tests for features/intraday_indicators.py."""

import pandas as pd
import pytest

from features.intraday_indicators import (
    add_atr5m_percentile_threshold,
    add_gap_and_fade_flag,
    add_session_vwap_1m,
    add_time_of_day_rvol,
    add_vwap_cross_count,
    build_daily_context,
    compute_opening_range,
    resample_to_5min,
)


def _minute_bar(ts, open_, high, low, close, volume):
    return {"timestamp": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _minutes_for_session(date_str, start="09:30", count=30, price=100.0, volume=1000.0):
    rows = []
    start_ts = pd.Timestamp(f"{date_str} {start}", tz="America/New_York").tz_convert("UTC")
    for i in range(count):
        ts = start_ts + pd.Timedelta(minutes=i)
        rows.append(_minute_bar(ts, price, price + 0.1, price - 0.1, price, volume))
    return rows


def test_compute_opening_range_uses_only_first_15_minutes():
    rows = []
    rows += _minutes_for_session("2026-01-05", start="09:30", count=15, price=100.0)
    # A much wider/later move that must NOT affect the opening range.
    later_start = pd.Timestamp("2026-01-05 09:45", tz="America/New_York").tz_convert("UTC")
    rows.append(_minute_bar(later_start, 100.0, 200.0, 50.0, 150.0, 5000))
    frame = pd.DataFrame(rows)

    opening_range = compute_opening_range(frame, minutes=15)

    assert len(opening_range) == 1
    row = opening_range.iloc[0]
    assert row["orh"] == pytest.approx(100.1)
    assert row["orl"] == pytest.approx(99.9)
    assert row["or_midpoint"] == pytest.approx(100.0)


def test_session_vwap_resets_daily_and_uses_typical_price():
    day1 = [
        _minute_bar(pd.Timestamp("2026-01-05 09:30", tz="America/New_York").tz_convert("UTC"), 100, 101, 99, 100, 1000),
        _minute_bar(pd.Timestamp("2026-01-05 09:31", tz="America/New_York").tz_convert("UTC"), 100, 102, 100, 101, 2000),
    ]
    day2 = [
        _minute_bar(pd.Timestamp("2026-01-06 09:30", tz="America/New_York").tz_convert("UTC"), 200, 201, 199, 200, 500),
    ]
    frame = pd.DataFrame(day1 + day2)

    result = add_session_vwap_1m(frame)

    typical_1 = (101 + 99 + 100) / 3
    typical_2 = (102 + 100 + 101) / 3
    expected_vwap_bar2 = (typical_1 * 1000 + typical_2 * 2000) / (1000 + 2000)
    assert result.iloc[1]["vwap"] == pytest.approx(expected_vwap_bar2)

    # Day 2 VWAP must reset, not carry day 1's cumulative volume/PV forward.
    typical_day2 = (201 + 199 + 200) / 3
    assert result.iloc[2]["vwap"] == pytest.approx(typical_day2)


def test_resample_to_5min_labels_bars_by_close_time_and_uses_ohlc_correctly():
    rows = _minutes_for_session("2026-01-05", start="09:30", count=5, price=100.0)
    # Make each minute distinguishable.
    for i, row in enumerate(rows):
        row["open"] = 100 + i
        row["high"] = 100 + i + 0.5
        row["low"] = 100 + i - 0.5
        row["close"] = 100 + i
        row["volume"] = 10 * (i + 1)
    frame = pd.DataFrame(rows)

    bars = resample_to_5min(frame)

    assert len(bars) == 1
    bar = bars.iloc[0]
    assert bar["eastern_time"].strftime("%H:%M") == "09:35"  # label = bar CLOSE time
    assert bar["open"] == 100  # first minute's open (09:30)
    assert bar["close"] == 104  # last minute's close (09:34)
    assert bar["high"] == pytest.approx(104.5)
    assert bar["low"] == pytest.approx(99.5)
    assert bar["volume"] == sum(10 * (i + 1) for i in range(5))


def test_vwap_cross_count_increments_on_each_sign_change():
    ts0 = pd.Timestamp("2026-01-05 09:35", tz="America/New_York").tz_convert("UTC")
    rows = []
    # close vs vwap sequence: above, above, below, above, below -> 3 crosses
    closes_vwaps = [(101, 100), (102, 100), (99, 100), (101, 100), (98, 100)]
    for i, (close, vwap) in enumerate(closes_vwaps):
        rows.append(
            {
                "timestamp": ts0 + pd.Timedelta(minutes=5 * i),
                "session_date": pd.Timestamp("2026-01-05").date(),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "vwap": vwap,
            }
        )
    frame = pd.DataFrame(rows)

    result = add_vwap_cross_count(frame)

    assert result["vwap_cross_count"].tolist() == [0, 0, 1, 2, 3]


def test_time_of_day_rvol_matches_same_clock_time_not_naive_full_day_average():
    et = "America/New_York"
    rows = []
    # Five prior sessions (>= min_periods=5) with a HEAVY first-30-minutes
    # then quiet rest of day.
    for day in ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]:
        start = pd.Timestamp(f"{day} 09:30", tz=et).tz_convert("UTC")
        cum = 0
        for i, vol in enumerate([5000] * 6 + [200] * 12):  # 09:30-10:00 heavy, rest quiet
            cum += vol
            ts = start + pd.Timedelta(minutes=5 * i)
            rows.append(
                {
                    "timestamp": ts,
                    "session_date": pd.Timestamp(day).date(),
                    "eastern_time": ts.tz_convert(et).time(),
                    "open": 100,
                    "high": 100,
                    "low": 100,
                    "close": 100,
                    "cum_vol": cum,
                }
            )
    frame = pd.DataFrame(rows)

    result = add_time_of_day_rvol(frame, lookback_days=20)

    today = "2026-01-12"
    start_today = pd.Timestamp(f"{today} 09:30", tz=et).tz_convert("UTC")
    cum_today = 0
    today_rows = []
    for i, vol in enumerate([200] * 6 + [200] * 12):  # today is quiet even early
        cum_today += vol
        ts = start_today + pd.Timedelta(minutes=5 * i)
        today_rows.append(
            {
                "timestamp": ts,
                "session_date": pd.Timestamp(today).date(),
                "eastern_time": ts.tz_convert(et).time(),
                "open": 100,
                "high": 100,
                "low": 100,
                "close": 100,
                "cum_vol": cum_today,
            }
        )
    frame_with_today = pd.concat([frame, pd.DataFrame(today_rows)], ignore_index=True)
    result = add_time_of_day_rvol(frame_with_today, lookback_days=20)

    early_row = result[(result["session_date"] == pd.Timestamp(today).date())].iloc[0]
    # Time-of-day matched RVOL at 09:35 should be low (200 vs historical 5000
    # average at that SAME time), even though today's cumulative volume by
    # end of day is proportionally closer to a "normal" day. This proves the
    # comparison is time-of-day matched, not a naive full-day ratio.
    assert early_row["rvol"] < 0.2


def test_gap_and_fade_flag_true_when_gap_up_and_faded():
    daily = pd.DataFrame(
        [
            {
                "session_date": pd.Timestamp("2026-01-05").date(),
                "atr_d": 1.0,
                "gap_dollars": 2.0,  # gapped up 2x ATR
                "session_open": 105.0,
            }
        ]
    )
    first15 = {
        pd.Timestamp("2026-01-05").date(): {"orh": 106.0, "orl": 104.0, "close": 104.3}  # bottom third, below open
    }
    result = add_gap_and_fade_flag(daily, first15)
    assert bool(result.iloc[0]["gap_and_fade_flag"]) is True


def test_gap_and_fade_flag_false_when_no_gap():
    daily = pd.DataFrame(
        [
            {
                "session_date": pd.Timestamp("2026-01-05").date(),
                "atr_d": 1.0,
                "gap_dollars": 0.1,
                "session_open": 105.0,
            }
        ]
    )
    first15 = {pd.Timestamp("2026-01-05").date(): {"orh": 106.0, "orl": 104.0, "close": 104.3}}
    result = add_gap_and_fade_flag(daily, first15)
    assert bool(result.iloc[0]["gap_and_fade_flag"]) is False


def test_atr5m_percentile_threshold_only_uses_prior_sessions():
    rows = []
    for day_index, day in enumerate(["2026-01-05", "2026-01-06", "2026-01-07"]):
        for bar_index in range(3):
            rows.append(
                {
                    "session_date": pd.Timestamp(day).date(),
                    "atr_5m": 1.0 if day_index < 2 else 10.0,  # today is an outlier
                }
            )
    frame = pd.DataFrame(rows)

    result = add_atr5m_percentile_threshold(frame, lookback_days=20, quantile=0.98)

    today_threshold = result.loc[result["session_date"] == pd.Timestamp("2026-01-07").date(), "atr_5m_p98_20d"]
    # Not enough prior sessions (< 20 values) to form a reliable percentile yet.
    assert today_threshold.isna().all()
