"""Production daemon: multi-TF signal scanner with Telegram alerts.

Wakes at every 15-minute bar close, fetches live bars for 4H / 1H / 15M,
runs cascaded strategy analysis, and fires a Telegram alert when 4H and 1H
agree on the same direction.  De-duplicates alerts per H4 bar.

Usage:
  python scripts/prod_daemon_xauusd.py \\
      --symbol XAUUSD \\
      [--lookback-4h 90] \\
      [--lookback-1h 45] \\
      [--lookback-15m 14] \\
      [--state-dir data/] \\
      [--log-file logs/daemon_XAUUSD.log]

Required env vars:
  TWELVEDATA_API_KEY   — never passed as a CLI arg or logged
  TELEGRAM_TOKEN       — never logged
  TELEGRAM_CHAT_ID     — never logged
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from novax.data.ingest.twelvedata import fetch_bars
from novax.engine import Signal
from novax.live import (
    AlertStateStore,
    BarScheduler,
    MultiTFScanner,
    MultiTFScanResult,
)

_shutdown = threading.Event()


def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
    _shutdown.set()


def _setup_logging(log_file: str | None) -> logging.Logger:
    log = logging.getLogger("prod_daemon_xauusd")
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        rh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        rh.setFormatter(fmt)
        log.addHandler(rh)
    return log


def _sleep_until(target: datetime) -> None:
    while not _shutdown.is_set():
        remaining = (target - datetime.now(tz=UTC)).total_seconds()
        if remaining <= 0:
            break
        _shutdown.wait(timeout=min(1.0, remaining))


def _send_telegram(token: str, chat_id: str, text: str, log: logging.Logger) -> None:
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
        f"?chat_id={urllib.parse.quote(chat_id)}"
        f"&text={urllib.parse.quote(text)}"
        f"&parse_mode=Markdown"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            if resp.status != 200:
                log.warning("Telegram returned HTTP %s", resp.status)
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram send failed: %s", exc)


def _format_telegram(result: MultiTFScanResult) -> str:
    direction = result.direction.value  # "LONG" or "SHORT"
    dir_emoji = "🟢" if result.direction == Signal.LONG else "🔴"

    sl_str = f"{result.sl:,.2f}" if result.sl is not None else "n/a"
    tp_str = f"{result.tp:,.2f}" if result.tp is not None else "n/a"

    rr_str = "n/a"
    if result.sl is not None and result.tp is not None and result.entry_price is not None:
        risk = abs(result.entry_price - result.sl)
        reward = abs(result.tp - result.entry_price)
        if risk > 0:
            rr_str = f"{reward / risk:.1f}"

    h1_emoji = "✅" if result.h1.signal == result.direction else "⚠️"
    m15_label = result.m15.signal.value if result.m15.signal != Signal.FLAT else "FLAT"

    entry_str = (
        f"{result.entry_price:,.2f}" if result.entry_price is not None else "n/a"
    )
    scan_str = result.scanned_at.strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"🔔 *{result.symbol} — Multi-TF Alert*",
        "",
        f"*Direction : {dir_emoji} {direction}*",
        "",
        f"4H BOS Retest : ✅ {result.h4.signal.value}",
        f"  SL : {sl_str}",
        f"  TP : {tp_str}  (RR {rr_str})",
        "",
        f"1H Pullback   : {h1_emoji} {result.h1.signal.value}  (confirmed)",
        f"15M EMA Cross : {m15_label}  ⏱ entry timing",
        "",
        f"Entry ref : {entry_str}",
        f"Scanned   : {scan_str}",
    ]
    return "\n".join(lines)


def _run_cycle(
    *,
    symbol: str,
    lookback_h4: int,
    lookback_h1: int,
    lookback_m15: int,
    state_dir: Path,
    scanner: MultiTFScanner,
    alert_store: AlertStateStore,
    api_key: str,
    telegram_token: str,
    telegram_chat_id: str,
    log: logging.Logger,
) -> None:
    now = datetime.now(tz=UTC)

    log.info(
        "Fetching %s bars — 4H:%dd  1H:%dd  15M:%dd",
        symbol, lookback_h4, lookback_h1, lookback_m15,
    )
    bars_h4 = fetch_bars(
        symbol=symbol,
        interval="4h",
        start=now - timedelta(days=lookback_h4),
        end=now,
        api_key=api_key,
    )
    bars_h1 = fetch_bars(
        symbol=symbol,
        interval="1h",
        start=now - timedelta(days=lookback_h1),
        end=now,
        api_key=api_key,
    )
    bars_m15 = fetch_bars(
        symbol=symbol,
        interval="15min",
        start=now - timedelta(days=lookback_m15),
        end=now,
        api_key=api_key,
    )
    log.info(
        "Bars fetched — 4H:%d  1H:%d  15M:%d",
        len(bars_h4),
        len(bars_h1),
        len(bars_m15),
    )

    result = scanner.scan(bars_h4, bars_h1, bars_m15)
    log.info(
        "[%s] 4H=%s 1H=%s 15M=%s conf=%s SL=%s TP=%s",
        symbol,
        result.h4.signal.value,
        result.h1.signal.value,
        result.m15.signal.value,
        result.confluence,
        f"{result.sl:.2f}" if result.sl is not None else "n/a",
        f"{result.tp:.2f}" if result.tp is not None else "n/a",
    )

    if result.confluence:
        state = alert_store.load()
        if state.is_duplicate(result.direction.value, result.h4.last_bar_ts):
            log.info(
                "No alert: same signal already sent for this H4 bar (%s)",
                result.h4.last_bar_ts,
            )
        else:
            msg = _format_telegram(result)
            _send_telegram(telegram_token, telegram_chat_id, msg, log)
            state.update(result.direction.value, result.h4.last_bar_ts)
            alert_store.save(state)
            log.info("Alert sent: %s %s", symbol, result.direction.value)
    else:
        log.info(
            "No confluence — 4H=%s 1H=%s",
            result.h4.signal.value,
            result.h1.signal.value,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-TF production daemon: 4H BOS + 1H Pullback + 15M EMA."
    )
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--lookback-4h", type=int, default=90)
    parser.add_argument("--lookback-1h", type=int, default=45)
    parser.add_argument("--lookback-15m", type=int, default=14)
    parser.add_argument("--state-dir", default="data/")
    parser.add_argument("--log-file", default=None)
    # H4 strategy params
    parser.add_argument("--ema-fast", type=int, default=20)
    parser.add_argument("--ema-slow", type=int, default=50)
    parser.add_argument("--ob-buffer-pips", type=float, default=5.0)
    parser.add_argument("--max-risk-pips", type=float, default=80.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
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

    log = _setup_logging(args.log_file)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    symbol = args.symbol.upper()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    alert_store = AlertStateStore(state_dir / f"alert_state_{symbol}.json")
    scanner = MultiTFScanner(
        symbol,
        h4_params={
            "ema_fast": args.ema_fast,
            "ema_slow": args.ema_slow,
            "ob_buffer_pips": args.ob_buffer_pips,
            "max_risk_pips": args.max_risk_pips,
            "risk_reward": args.risk_reward,
        },
    )

    log.info("Daemon started — %s  state-dir=%s", symbol, state_dir)

    sched = BarScheduler(900)
    while not _shutdown.is_set():
        nxt = sched.next_bar_close(datetime.now(tz=UTC))
        log.info("Next 15M close: %s UTC — sleeping …", nxt.strftime("%Y-%m-%d %H:%M:%S"))
        _sleep_until(nxt)

        if _shutdown.is_set():
            break

        try:
            _run_cycle(
                symbol=symbol,
                lookback_h4=args.lookback_4h,
                lookback_h1=args.lookback_1h,
                lookback_m15=args.lookback_15m,
                state_dir=state_dir,
                scanner=scanner,
                alert_store=alert_store,
                api_key=api_key,
                telegram_token=telegram_token,
                telegram_chat_id=telegram_chat_id,
                log=log,
            )
        except Exception:  # noqa: BLE001
            log.exception("Cycle error — will retry at next 15M close")

    log.info("Daemon stopped.")


if __name__ == "__main__":
    main()
