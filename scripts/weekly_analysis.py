"""One-shot pre-market weekly analysis — sends a Telegram summary.

Run every Sunday at 21:00 UTC before markets open at 22:00 UTC.

Usage:
  python scripts/weekly_analysis.py \\
      --symbol XAUUSD \\
      [--lookback-days 30]

Required env vars:
  TWELVEDATA_API_KEY   — never logged or printed
  TELEGRAM_TOKEN       — never logged
  TELEGRAM_CHAT_ID     — never logged
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from novax.data.ingest.twelvedata import fetch_bars
from novax.engine import BarView, Position, Signal
from novax.strategies.weekly_bos_retest import WeeklyBOSRetest


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
        f"?chat_id={urllib.parse.quote(chat_id)}"
        f"&text={urllib.parse.quote(text)}"
        f"&parse_mode=Markdown"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            if resp.status != 200:
                print(f"WARN: Telegram returned HTTP {resp.status}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Telegram send failed: {exc}", file=sys.stderr)


def _bos_label(state: str) -> str:
    return {
        "bos_up": "BOS_UP (bullish institutional bias)",
        "bos_down": "BOS_DOWN (bearish institutional bias)",
        "idle": "IDLE (no confirmed break yet)",
    }.get(state.lower(), state)


def _build_message(
    symbol: str,
    bos_state: str,
    has_ob: bool,
    ob_high: float | None,
    ob_low: float | None,
    prev_high: float | None,
    prev_low: float | None,
    last_close: float,
    last_signal: Signal,
    week_start: datetime,
) -> str:
    week_str = week_start.strftime("%Y-%m-%d")
    bias = last_signal.value if last_signal != Signal.FLAT else "NEUTRAL"

    lines: list[str] = [
        f"📊 *{symbol} Weekly Pre-Market Analysis*",
        f"Week starting: {week_str}",
        "",
        f"BOS State    : {_bos_label(bos_state)}",
    ]

    if prev_high is not None and prev_low is not None:
        week_range = prev_high - prev_low
        lines.append(
            f"Prev Week H/L: {prev_high:,.2f} / {prev_low:,.2f}"
            f"  (range: ${week_range:.2f})"
        )

    lines.append(f"Last 4H close: {last_close:,.2f}")
    lines.append("")

    if has_ob and ob_high is not None and ob_low is not None:
        lines.append(f"Order Block  : YES  ({ob_low:,.2f} – {ob_high:,.2f})")
    else:
        lines.append("Order Block  : none detected")

    lines.append(f"Current bias : {bias}")
    lines.append("")
    lines.append("Key levels this week:")

    if prev_high is not None:
        lines.append(f"  Resistance : {prev_high:,.2f}  (prev week high)")
    if prev_low is not None:
        lines.append(f"  Support    : {prev_low:,.2f}  (prev week low)")
    if has_ob and ob_high is not None and ob_low is not None:
        lines.append(f"  OB zone    : {ob_low:,.2f} – {ob_high:,.2f}")

    lines.append("")
    if bos_state.lower() == "idle":
        lines.append("Watch for: No clear directional bias — monitor for BOS this week.")
    elif bos_state.lower() == "bos_up":
        ob_note = (
            "retest of OB zone → LONG entry opportunity"
            if has_ob else "pullback to support → LONG"
        )
        lines.append(f"Watch for: BOS_UP {ob_note}")
    else:
        ob_note = (
            "retest of OB zone → SHORT entry opportunity"
            if has_ob else "bounce from resistance → SHORT"
        )
        lines.append(f"Watch for: BOS_DOWN {ob_note}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-market weekly analysis — sends a Telegram outlook."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args()

    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        print("ERROR: TWELVEDATA_API_KEY env var is not set.", file=sys.stderr)
        sys.exit(1)

    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not telegram_token or not telegram_chat_id:
        print(
            "ERROR: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars are required.",
            file=sys.stderr,
        )
        sys.exit(1)

    symbol = args.symbol.upper()
    now = datetime.now(tz=UTC)
    print(f"Running weekly analysis for {symbol} ({args.lookback_days}d lookback) …")

    bars = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=args.lookback_days),
        end=now,
        api_key=api_key,
    )
    if not bars:
        print("ERROR: no bars returned — check symbol and API key.", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(bars)} bars fetched  [{bars[0].ts.date()} → {bars[-1].ts.date()}]")

    strat = WeeklyBOSRetest()
    flat = Position(direction="FLAT")
    last_signal = Signal.FLAT
    for i in range(len(bars)):
        view = BarView(bars=tuple(bars[: i + 1]))
        last_signal = strat.on_bar(view, flat)

    bos_result = strat._bos.value  # noqa: SLF001
    weekly_levels = strat._weekly.value  # noqa: SLF001

    bos_state = bos_result.state.value if bos_result is not None else "idle"
    has_ob = bos_result.has_ob if bos_result is not None else False
    ob_high = bos_result.ob_high if (bos_result is not None and has_ob) else None
    ob_low = bos_result.ob_low if (bos_result is not None and has_ob) else None
    prev_high = weekly_levels.prev_high if weekly_levels is not None else None
    prev_low = weekly_levels.prev_low if weekly_levels is not None else None
    last_close = bars[-1].close

    # Next Monday as week-start reference
    days_until_monday = (7 - now.weekday()) % 7 or 7
    week_start = (now + timedelta(days=days_until_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    msg = _build_message(
        symbol=symbol,
        bos_state=bos_state,
        has_ob=has_ob,
        ob_high=ob_high,
        ob_low=ob_low,
        prev_high=prev_high,
        prev_low=prev_low,
        last_close=last_close,
        last_signal=last_signal,
        week_start=week_start,
    )

    print("\n" + msg + "\n")
    _send_telegram(telegram_token, telegram_chat_id, msg)
    print("Telegram message sent.")


if __name__ == "__main__":
    main()
