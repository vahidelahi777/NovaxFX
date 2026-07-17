"""Tests for the A3 onboarding flow — pure state machine and keyboard builders.

No telegram dependency; everything tested here is in novax.bot.onboarding (pure).
"""

from __future__ import annotations

import pytest

from novax.bot import (
    AVAILABLE_PAIRS,
    AVAILABLE_SESSIONS,
    CB_DONE,
    CB_PREFIX_PAIR,
    CB_PREFIX_SCORE,
    CB_PREFIX_SES,
    SCORE_OPTIONS,
    OnboardingStep,
    UserPrefs,
    advance_pairs,
    advance_sessions,
    initial_state,
    pairs_keyboard,
    prefs_to_state,
    score_keyboard,
    sessions_keyboard,
    set_score,
    state_to_prefs,
    toggle_pair,
    toggle_session,
)

# ---- initial state ----------------------------------------------------------


def test_initial_state_defaults() -> None:
    state = initial_state()
    assert state.step is OnboardingStep.PAIRS
    assert state.selected_pairs == frozenset()
    assert state.selected_sessions == frozenset()
    assert state.selected_score is None


# ---- toggle_pair ------------------------------------------------------------


def test_toggle_pair_adds_and_removes() -> None:
    state = initial_state()
    state = toggle_pair(state, "XAUUSD")
    assert "XAUUSD" in state.selected_pairs
    state = toggle_pair(state, "XAUUSD")
    assert "XAUUSD" not in state.selected_pairs


def test_toggle_pair_unknown_is_noop() -> None:
    state = initial_state()
    unchanged = toggle_pair(state, "BTCUSD")
    assert unchanged == state


def test_toggle_pair_multiple() -> None:
    state = initial_state()
    for pair in ("EURUSD", "XAUUSD"):
        state = toggle_pair(state, pair)
    assert state.selected_pairs == frozenset({"EURUSD", "XAUUSD"})


# ---- toggle_session ---------------------------------------------------------


def test_toggle_session_adds_and_removes() -> None:
    state = initial_state()
    state = toggle_session(state, "LONDON")
    assert "LONDON" in state.selected_sessions
    state = toggle_session(state, "LONDON")
    assert "LONDON" not in state.selected_sessions


def test_toggle_session_unknown_is_noop() -> None:
    state = initial_state()
    unchanged = toggle_session(state, "SYDNEY")
    assert unchanged == state


# ---- advance_pairs ----------------------------------------------------------


def test_advance_pairs_raises_when_empty() -> None:
    with pytest.raises(ValueError, match="at least one pair"):
        advance_pairs(initial_state())


def test_advance_pairs_moves_to_sessions_step() -> None:
    state = toggle_pair(initial_state(), "XAUUSD")
    state = advance_pairs(state)
    assert state.step is OnboardingStep.SESSIONS
    assert "XAUUSD" in state.selected_pairs  # selection preserved


# ---- advance_sessions -------------------------------------------------------


def test_advance_sessions_raises_when_empty() -> None:
    state = toggle_pair(initial_state(), "XAUUSD")
    state = advance_pairs(state)
    with pytest.raises(ValueError, match="at least one session"):
        advance_sessions(state)


def test_advance_sessions_moves_to_score_step() -> None:
    state = toggle_pair(initial_state(), "XAUUSD")
    state = advance_pairs(state)
    state = toggle_session(state, "NEWYORK")
    state = advance_sessions(state)
    assert state.step is OnboardingStep.SCORE


# ---- set_score --------------------------------------------------------------


def test_set_score_marks_done() -> None:
    state = initial_state()
    state = set_score(state, 70)
    assert state.selected_score == 70
    assert state.step is OnboardingStep.DONE


def test_set_score_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="score must be one of"):
        set_score(initial_state(), 55)


# ---- state_to_prefs ---------------------------------------------------------


def test_state_to_prefs_uses_selected_values() -> None:
    state = initial_state()
    state = toggle_pair(state, "EURUSD")
    state = toggle_session(state, "LONDON")
    state = set_score(state, 80)
    prefs = state_to_prefs(state)
    assert prefs.pairs == frozenset({"EURUSD"})
    assert prefs.sessions == frozenset({"LONDON"})
    assert prefs.min_score == 80


def test_state_to_prefs_uses_defaults_when_empty() -> None:
    prefs = state_to_prefs(initial_state())
    assert prefs.pairs == frozenset({"XAUUSD"})
    assert prefs.sessions == frozenset({"LONDON", "NEWYORK"})
    assert prefs.min_score == 70


# ---- prefs_to_state ---------------------------------------------------------


def test_prefs_to_state_pre_populates() -> None:
    prefs = UserPrefs(pairs=frozenset({"GBPUSD"}), sessions=frozenset({"ASIA"}), min_score=60)
    state = prefs_to_state(prefs)
    assert state.selected_pairs == frozenset({"GBPUSD"})
    assert state.selected_sessions == frozenset({"ASIA"})
    assert state.selected_score == 60
    assert state.step is OnboardingStep.PAIRS  # always starts at pairs for re-edit


def test_prefs_to_state_roundtrips() -> None:
    prefs = UserPrefs(
        pairs=frozenset({"XAUUSD", "EURUSD"}), sessions=frozenset({"NEWYORK"}), min_score=70
    )
    assert state_to_prefs(prefs_to_state(prefs)) == prefs


# ---- keyboard builders ------------------------------------------------------


def test_pairs_keyboard_has_all_pairs_and_done() -> None:
    state = initial_state()
    rows = pairs_keyboard(state)
    labels = [row[0][0] for row in rows]
    for pair in AVAILABLE_PAIRS:
        assert any(pair in label for label in labels)
    assert any("Done" in label for label in labels)


def test_pairs_keyboard_shows_checkmark_for_selected() -> None:
    state = toggle_pair(initial_state(), "XAUUSD")
    rows = pairs_keyboard(state)
    xau_label = next(row[0][0] for row in rows if "XAUUSD" in row[0][0])
    assert "✅" in xau_label
    eur_label = next(row[0][0] for row in rows if "EURUSD" in row[0][0])
    assert "✅" not in eur_label


def test_pairs_keyboard_done_callback_data() -> None:
    rows = pairs_keyboard(initial_state())
    done_row = rows[-1]
    _, cb = done_row[0]
    assert cb == CB_PREFIX_PAIR + CB_DONE


def test_sessions_keyboard_has_all_sessions_and_done() -> None:
    state = initial_state()
    rows = sessions_keyboard(state)
    # Verify each session has a button (checked via callback data, not display label)
    cbs = [row[0][1] for row in rows]
    for ses in AVAILABLE_SESSIONS:
        assert any(ses in cb for cb in cbs)
    labels = [row[0][0] for row in rows]
    assert any("Done" in label for label in labels)


def test_sessions_keyboard_shows_checkmark_for_selected() -> None:
    state = toggle_session(initial_state(), "LONDON")
    rows = sessions_keyboard(state)
    lon_label = next(row[0][0] for row in rows if "LONDON" in row[0][0])
    assert "✅" in lon_label


def test_sessions_keyboard_done_callback_data() -> None:
    rows = sessions_keyboard(initial_state())
    done_row = rows[-1]
    _, cb = done_row[0]
    assert cb == CB_PREFIX_SES + CB_DONE


def test_score_keyboard_covers_all_options() -> None:
    rows = score_keyboard()
    all_cbs = [cb for row in rows for _, cb in row]
    for score in SCORE_OPTIONS:
        assert CB_PREFIX_SCORE + str(score) in all_cbs


def test_score_keyboard_two_rows() -> None:
    rows = score_keyboard()
    assert len(rows) == 2
    assert len(rows[0]) == 3
    assert len(rows[1]) == 2


# ---- callback-data constants ------------------------------------------------


def test_cb_prefixes_are_distinct() -> None:
    prefixes = {CB_PREFIX_PAIR, CB_PREFIX_SES, CB_PREFIX_SCORE}
    assert len(prefixes) == 3


def test_cb_done_not_a_valid_pair_or_session() -> None:
    assert CB_DONE not in AVAILABLE_PAIRS
    assert CB_DONE not in AVAILABLE_SESSIONS


# ---- full happy path --------------------------------------------------------


def test_full_onboarding_happy_path() -> None:
    state = initial_state()
    state = toggle_pair(state, "XAUUSD")
    state = toggle_pair(state, "EURUSD")
    state = advance_pairs(state)
    state = toggle_session(state, "LONDON")
    state = toggle_session(state, "NEWYORK")
    state = advance_sessions(state)
    state = set_score(state, 70)
    assert state.step is OnboardingStep.DONE
    prefs = state_to_prefs(state)
    assert prefs.pairs == frozenset({"XAUUSD", "EURUSD"})
    assert prefs.sessions == frozenset({"LONDON", "NEWYORK"})
    assert prefs.min_score == 70
