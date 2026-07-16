"""Static text for the NovaxFX product bot (Phase 0 · A1).

Pure functions only — no network, no side effects. Kept separate from the
python-telegram-bot wiring in ``app.py`` so this module is fully unit-testable
without the optional ``bot`` dependency installed.

The single-source ``DISCLAIMER`` is appended to user-facing surfaces (task G1
will reuse it everywhere).
"""

from __future__ import annotations

__all__ = [
    "DISCLAIMER",
    "disclaimer_text",
    "help_text",
    "render_command",
    "start_text",
    "unknown_text",
]

# Single source of truth for the risk/legal line — see decision D-005 / task G1.
DISCLAIMER = (
    "⚠️ Risk & legal — NovaxFX provides general market information and education, "
    "not personalized financial advice. Trading FX/CFDs carries a substantial risk "
    "of loss. Past performance does not guarantee future results. No profit is "
    "promised. Any bot-trading runs only on your own broker account, with your own "
    "keys — NovaxFX never holds or moves your funds. You are solely responsible for "
    "your decisions."
)

_PILLARS = (
    "• 📚 Learn — structured lessons on sessions, structure, and risk\n"
    "• 🔍 Analyze — on-demand multi-timeframe reads and market context\n"
    "• 📡 Signals — validated entries with a 0–100 confidence score and the why\n"
    "• 🤖 Bot-trading — opt-in, on your own broker account (coming soon)"
)


def start_text(first_name: str | None = None) -> str:
    """Welcome message shown on /start."""
    greeting = f"Welcome, {first_name}!" if first_name else "Welcome!"
    return (
        f"👋 {greeting}\n\n"
        "This is *NovaxFX* — the honest FX signals platform. Every edge is "
        "validated before you ever see it.\n\n"
        f"{_PILLARS}\n\n"
        "Type /help to see everything I can do, or /disclaimer for the fine print.\n\n"
        f"{DISCLAIMER}"
    )


def help_text() -> str:
    """Command reference shown on /help."""
    return (
        "*NovaxFX — commands*\n\n"
        "/start — introduction and setup\n"
        "/help — this list\n"
        "/disclaimer — risk & legal notice\n\n"
        "_Coming soon:_ /analyze <pair>, /signals, /learn, /settings, /connect."
    )


def disclaimer_text() -> str:
    """Full risk/legal notice shown on /disclaimer."""
    return f"*NovaxFX — risk & legal*\n\n{DISCLAIMER}"


def unknown_text() -> str:
    """Reply for an unrecognised command."""
    return "I don't recognise that command. Type /help to see what I can do."


def render_command(command: str, first_name: str | None = None) -> str:
    """Pure router: map a bare command name to its reply text.

    ``command`` is the command without the leading slash (e.g. ``"start"``).
    Used by the handlers in ``app.py`` and directly by unit tests.
    """
    normalized = command.lstrip("/").lower()
    if normalized == "start":
        return start_text(first_name)
    if normalized == "help":
        return help_text()
    if normalized == "disclaimer":
        return disclaimer_text()
    return unknown_text()
