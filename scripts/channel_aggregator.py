"""Telegram channel signal aggregator.

Listens to one or more public Telegram channels, parses each message (text +
chart images) with Claude AI, and forwards confirmed trading signals to the
Novax trading channel.

Usage (first run — requires interactive phone auth):
  python scripts/channel_aggregator.py \\
      --channels @channel1 @channel2 \\
      [--session-file data/aggregator.session] \\
      [--log-file logs/aggregator.log]

Subsequent runs reuse the saved session file (no phone prompt).

Required env vars:
  TELEGRAM_API_ID          — from https://my.telegram.org (integer)
  TELEGRAM_API_HASH        — from https://my.telegram.org (string, never logged)
  TELEGRAM_PHONE           — your phone number e.g. +1234567890
  TELEGRAM_CHAT_ID         — output channel (your Novax trading channel)
  TELEGRAM_TOKEN           — Novax bot token for sending output
  ANTHROPIC_API_KEY        — Claude API key (never logged)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import logging.handlers
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

_DEPS_OK = True
try:
    import anthropic
    from telethon import TelegramClient, events
    from telethon.tl.types import MessageMediaPhoto
except ImportError:
    _DEPS_OK = False

if TYPE_CHECKING:
    import anthropic  # noqa: F811
    from telethon import TelegramClient, events  # noqa: F811
    from telethon.tl.types import MessageMediaPhoto  # noqa: F811


# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

_PARSE_PROMPT = """\
You are a trading signal parser for a professional FX/Gold trading desk.

Analyze the Telegram message below (and any chart screenshot provided).
Determine whether it contains a specific, actionable trading signal.

Return ONLY valid JSON — no markdown, no explanation:
{
  "is_signal": true | false,
  "symbol": "XAUUSD" | "EURUSD" | "GBPUSD" | "other symbol" | null,
  "direction": "LONG" | "SHORT" | null,
  "entry": <float or null>,
  "sl": <float or null>,
  "tp": <float or null>,
  "tp2": <float or null>,
  "rationale": "<one-sentence summary of the setup>",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}

Rules:
- is_signal = false for general commentary, news, educational content, or vague calls
- is_signal = true only when there is a clear direction AND at least SL or TP
- entry may be null if the analyst says "market price" or "current price"
- If multiple TPs are given, put the first as tp and second as tp2
- confidence HIGH = explicit levels + clear setup rationale
- confidence MEDIUM = levels present but setup is vague or contradictory
- confidence LOW = direction only, no levels or very unclear

Message text:
{message}
"""

_MODEL_TEXT  = "claude-haiku-4-5-20251001"   # cheap + fast for text-only
_MODEL_IMAGE = "claude-sonnet-4-6"            # vision model for charts


# ---------------------------------------------------------------------------
# Signal deduplication: ignore identical (symbol, direction) within 1 hour
# ---------------------------------------------------------------------------

class _RecentSignals:
    def __init__(self, window_seconds: int = 3600) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._seen: dict[tuple[str, str], datetime] = {}

    def is_duplicate(self, symbol: str, direction: str) -> bool:
        key = (symbol.upper(), direction.upper())
        now = datetime.now(tz=UTC)
        last = self._seen.get(key)
        if last is not None and (now - last) < self._window:
            return True
        self._seen[key] = now
        return False

    def _evict(self) -> None:
        now = datetime.now(tz=UTC)
        self._seen = {k: v for k, v in self._seen.items()
                      if (now - v) < self._window}


# ---------------------------------------------------------------------------
# Claude parser
# ---------------------------------------------------------------------------

def _parse_signal(
    client_ai: anthropic.Anthropic,
    text: str,
    image_bytes: bytes | None,
    source: str,
    log: logging.Logger,
) -> dict[str, Any] | None:
    """Send message to Claude and return parsed signal dict, or None on failure."""
    prompt = _PARSE_PROMPT.replace("{message}", text or "(no text)")

    try:
        if image_bytes is not None:
            b64 = base64.standard_b64encode(image_bytes).decode()
            response = client_ai.messages.create(
                model=_MODEL_IMAGE,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        else:
            response = client_ai.messages.create(
                model=_MODEL_TEXT,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )

        raw = response.content[0].text.strip()
        result: dict[str, Any] = json.loads(raw)
        log.debug("[%s] Claude parsed: %s", source, result)
        return result

    except json.JSONDecodeError:
        log.warning("[%s] Claude returned non-JSON: %s", source, raw[:200])
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] Claude call failed: %s", source, exc)

    return None


# ---------------------------------------------------------------------------
# Telegram output (reuse simple HTTP sender — no bot SDK needed)
# ---------------------------------------------------------------------------

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
                log.warning("Telegram output returned HTTP %s", resp.status)
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram output send failed: %s", exc)


# ---------------------------------------------------------------------------
# Signal formatter
# ---------------------------------------------------------------------------

def _fmt_external_signal(parsed: dict[str, Any], source: str, scanned_at: datetime) -> str:
    direction = parsed.get("direction", "?")
    symbol    = parsed.get("symbol") or "?"
    entry     = parsed.get("entry")
    sl        = parsed.get("sl")
    tp        = parsed.get("tp")
    tp2       = parsed.get("tp2")
    rationale = parsed.get("rationale") or ""
    confidence = parsed.get("confidence", "?")

    dir_emoji = "🟢" if direction == "LONG" else "🔴" if direction == "SHORT" else "⚪"

    entry_str = f"{entry:,.2f}" if entry is not None else "market"
    sl_str    = f"{sl:,.2f}"   if sl is not None  else "n/a"
    tp_str    = f"{tp:,.2f}"   if tp is not None  else "n/a"

    rr_str = "n/a"
    if entry is not None and sl is not None and tp is not None:
        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        if risk > 0:
            rr_str = f"{reward / risk:.1f}"

    lines = [
        f"📡 *{symbol} — External Signal*",
        f"_Source: {source}_",
        "",
        f"*Direction : {dir_emoji} {direction}*",
        "",
        f"Entry : {entry_str}",
        f"SL    : {sl_str}",
        f"TP    : {tp_str}",
    ]
    if tp2 is not None:
        lines.append(f"TP2   : {tp2:,.2f}")
    lines += [
        f"RR    : {rr_str}",
        "",
        f"_Setup: {rationale}_",
        f"_Confidence: {confidence}_",
        f"_Received: {scanned_at.strftime('%Y-%m-%d %H:%M UTC')}_",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def _setup_logging(log_file: str | None) -> logging.Logger:
    log = logging.getLogger("channel_aggregator")
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run(args: argparse.Namespace, log: logging.Logger) -> None:
    api_id    = int(os.environ["TELEGRAM_API_ID"])
    api_hash  = os.environ["TELEGRAM_API_HASH"]
    phone     = os.environ["TELEGRAM_PHONE"]
    out_token = os.environ["TELEGRAM_TOKEN"]
    out_chat  = os.environ["TELEGRAM_CHAT_ID"]
    ai_key    = os.environ["ANTHROPIC_API_KEY"]

    client_ai   = anthropic.Anthropic(api_key=ai_key)
    recent      = _RecentSignals(window_seconds=3600)
    session_path = args.session_file

    channels: list[str] = args.channels
    log.info("Listening on %d channel(s): %s", len(channels), channels)

    client = TelegramClient(session_path, api_id, api_hash)
    await client.start(phone=phone)
    log.info("Telethon session active — watching channels")

    @client.on(events.NewMessage(chats=channels))  # type: ignore[misc]
    async def _on_message(event: events.NewMessage.Event) -> None:
        msg     = event.message
        text    = msg.text or ""
        source  = getattr(event.chat, "username", None) or str(event.chat_id)
        now     = datetime.now(tz=UTC)

        # Download image if attached
        image_bytes: bytes | None = None
        if msg.media and isinstance(msg.media, MessageMediaPhoto):
            try:
                buf = io.BytesIO()
                await client.download_media(msg.media, file=buf)
                image_bytes = buf.getvalue()
                log.debug("[%s] Downloaded image: %d bytes", source, len(image_bytes))
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] Image download failed: %s", source, exc)

        if not text and image_bytes is None:
            return  # nothing to parse

        log.info("[%s] New message (len=%d, image=%s)", source, len(text), image_bytes is not None)

        parsed = _parse_signal(client_ai, text, image_bytes, source, log)
        if parsed is None:
            return

        if not parsed.get("is_signal"):
            log.info("[%s] Not a signal — skipped", source)
            return

        symbol    = parsed.get("symbol") or "UNKNOWN"
        direction = parsed.get("direction") or "UNKNOWN"
        confidence = parsed.get("confidence", "LOW")

        if confidence == "LOW":
            log.info("[%s] Low-confidence signal skipped (%s %s)", source, symbol, direction)
            return

        if recent.is_duplicate(symbol, direction):
            log.info("[%s] Duplicate %s %s within 1H — skipped", source, symbol, direction)
            return

        recent._evict()  # noqa: SLF001

        msg_out = _fmt_external_signal(parsed, source, now)
        _send_telegram(out_token, out_chat, msg_out, log)
        log.info("Signal forwarded: [%s] %s %s conf=%s", source, symbol, direction, confidence)

    await client.run_until_disconnected()


def main() -> None:
    if not _DEPS_OK:
        print(
            "ERROR: Missing dependencies. Install with:\n"
            "  pip install telethon anthropic",
            file=sys.stderr,
        )
        sys.exit(1)

    required_vars = [
        "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE",
        "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY",
    ]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Telegram channel signal aggregator")
    parser.add_argument(
        "--channels", nargs="+", required=True,
        metavar="@channel",
        help="One or more public channel usernames, e.g. @goldanalysis @forexsignals",
    )
    parser.add_argument(
        "--session-file", default="data/aggregator.session",
        help="Path for Telethon session file (persisted after first auth)",
    )
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    log = _setup_logging(args.log_file)

    asyncio.run(_run(args, log))


if __name__ == "__main__":
    main()
