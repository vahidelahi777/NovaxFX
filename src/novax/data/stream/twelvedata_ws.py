"""TwelveData WebSocket real-time tick stream → OHLCV bar builder.

Replaces the polling fetch_bars() daemon loop with a persistent WebSocket
connection.  Ticks arrive per-trade; this module accumulates them into
bars of a fixed interval and emits completed bars via a callback.

Requirements
------------
pip install "twelvedata[websocket]"   # adds websocket-client dependency
TwelveData Pro plan or above          # WebSocket not available on Basic

Threading model
---------------
The TwelveData SDK runs the WebSocket in a daemon thread.  _on_tick() is
called from that thread, so the BarBuilder uses a Lock for every mutation.
The completed-bar callback is also called from that thread; keep it fast
(hand off to a queue if heavy work is needed).

Usage
-----
    from novax.data.stream.twelvedata_ws import TwelveDataStream

    def on_bar(bar: Bar) -> None:
        # called on every completed 15M bar — run your scanner here
        scanner.scan(...)

    stream = TwelveDataStream(
        api_key=os.environ["TWELVEDATA_API_KEY"],
        symbols=["XAU/USD", "EUR/USD"],
        interval_seconds=900,       # 15 minutes
        on_bar=on_bar,
    )
    stream.start()
    # ... main thread does other work or sleeps ...
    stream.stop()
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ...data_sources import Bar
from ...instruments import get_instrument

__all__ = ["TwelveDataStream", "BarBuilder"]

log = logging.getLogger(__name__)


def _bar_open_ts(tick_ts: int, interval_seconds: int) -> datetime:
    """Floor a Unix timestamp to the nearest bar-open boundary."""
    floored = (tick_ts // interval_seconds) * interval_seconds
    return datetime.fromtimestamp(floored, tz=UTC)


class BarBuilder:
    """Accumulates ticks into a single OHLCV bar.

    When the first tick of a new interval arrives, the previous bar is
    complete and emitted via on_complete.
    """

    def __init__(
        self,
        symbol: str,
        interval_seconds: int,
        on_complete: Callable[[Bar], None],
    ) -> None:
        self._symbol = symbol
        self._interval = interval_seconds
        self._on_complete = on_complete
        self._lock = threading.Lock()

        # Current open bar state (None = no bar started yet)
        self._bar_ts: datetime | None = None
        self._open: float = 0.0
        self._high: float = 0.0
        self._low: float = float("inf")
        self._close: float = 0.0
        self._volume: float = 0.0
        self._bid: float = 0.0
        self._ask: float = 0.0
        self._tick_count: int = 0

        try:
            self._pip_size = get_instrument(symbol).pip_size
        except Exception:
            self._pip_size = 0.0001

    def push(self, event: dict[str, Any]) -> None:
        """Feed a raw WebSocket price event. Thread-safe."""
        if event.get("event") != "price":
            return
        try:
            price = float(event["price"])
            bid = float(event.get("bid") or price)
            ask = float(event.get("ask") or price)
            volume = float(event.get("last_volume") or 0)
            tick_ts = int(event.get("timestamp") or event.get("last_trade_time", 0))
        except (KeyError, ValueError, TypeError) as exc:
            log.debug("Skipping malformed tick: %s — %s", event, exc)
            return

        bar_ts = _bar_open_ts(tick_ts, self._interval)

        with self._lock:
            if self._bar_ts is None:
                # First tick ever — start the first bar
                self._start_bar(bar_ts, price, bid, ask, volume)
                return

            if bar_ts > self._bar_ts:
                # New bar interval started → emit the completed bar first
                self._emit()
                self._start_bar(bar_ts, price, bid, ask, volume)
            else:
                # Same bar — accumulate
                self._high = max(self._high, price)
                self._low = min(self._low, price)
                self._close = price
                self._volume += volume
                self._bid = bid
                self._ask = ask
                self._tick_count += 1

    def _start_bar(
        self,
        bar_ts: datetime,
        price: float,
        bid: float,
        ask: float,
        volume: float,
    ) -> None:
        self._bar_ts = bar_ts
        self._open = price
        self._high = price
        self._low = price
        self._close = price
        self._volume = volume
        self._bid = bid
        self._ask = ask
        self._tick_count = 1

    def _emit(self) -> None:
        if self._bar_ts is None or self._tick_count == 0:
            return
        spread = self._ask - self._bid
        bar = Bar(
            ts=self._bar_ts,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            bid=self._bid,
            ask=self._ask,
            spread=spread if spread > 0 else self._pip_size,
            source="twelvedata_ws",
        )
        log.debug(
            "Bar complete: %s %s O=%.5f H=%.5f L=%.5f C=%.5f ticks=%d",
            self._symbol, self._bar_ts.strftime("%H:%M UTC"),
            bar.open, bar.high, bar.low, bar.close, self._tick_count,
        )
        try:
            self._on_complete(bar)
        except Exception:
            log.exception("on_complete callback raised for %s", self._symbol)


class TwelveDataStream:
    """Manages a TwelveData WebSocket connection for one or more symbols.

    Each symbol gets its own BarBuilder.  Completed bars are emitted to
    the on_bar callback with the symbol name prepended.

    Example
    -------
    ::

        def on_bar(symbol: str, bar: Bar) -> None:
            print(f"{symbol} bar closed: {bar.close:.5f}")

        stream = TwelveDataStream(
            api_key="...",
            symbols=["XAU/USD", "EUR/USD"],
            interval_seconds=900,
            on_bar=on_bar,
        )
        stream.start()
    """

    def __init__(
        self,
        api_key: str,
        symbols: list[str],
        interval_seconds: int,
        on_bar: Callable[[str, Bar], None],
        heartbeat_interval: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._symbols = symbols
        self._interval = interval_seconds
        self._on_bar = on_bar
        self._heartbeat_interval = heartbeat_interval

        self._builders: dict[str, BarBuilder] = {
            sym: BarBuilder(sym, interval_seconds, lambda b, s=sym: on_bar(s, b))
            for sym in symbols
        }
        self._ws: Any = None
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Connect to TwelveData WebSocket and start streaming."""
        try:
            from twelvedata import TDClient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "Install the WebSocket extra: pip install 'twelvedata[websocket]'"
            ) from exc

        td = TDClient(apikey=self._api_key)
        self._ws = td.websocket(
            symbols=self._symbols,
            on_event=self._on_event,
        )
        self._ws.connect()
        log.info(
            "TwelveDataStream connected — symbols=%s interval=%ds",
            self._symbols, self._interval,
        )

        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="td-ws-heartbeat"
        )
        self._heartbeat_thread.start()

    def stop(self) -> None:
        """Disconnect and stop the heartbeat thread."""
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.disconnect()
            except Exception:
                pass
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
        log.info("TwelveDataStream disconnected.")

    def _on_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event")

        if event_type == "price":
            symbol = event.get("symbol", "")
            builder = self._builders.get(symbol)
            if builder:
                builder.push(event)
            else:
                log.debug("No builder for symbol: %s", symbol)

        elif event_type == "error":
            log.error(
                "TwelveData WS error %s: %s",
                event.get("code"), event.get("message"),
            )

        elif event_type in ("subscribe-status", "heartbeat", "ping"):
            log.debug("WS event: %s", event)

        else:
            log.debug("Unknown WS event: %s", event)

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(timeout=self._heartbeat_interval):
            if self._ws is not None:
                try:
                    self._ws.heartbeat()
                    log.debug("Heartbeat sent")
                except Exception as exc:
                    log.warning("Heartbeat failed: %s", exc)
