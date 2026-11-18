"""Helpers for driving dashboard pages through Streamlit's test harness, offline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "app"
VIEWS = sorted((APP / "views").glob("*.py"))
SYNTH = "Synthetic demo data"
LIVE = "Yahoo Finance daily data"
USER = "My own CSV files"


def view(name: str) -> Path:
    return APP / "views" / f"{name}.py"


def render(script, monkeypatch, **state) -> AppTest:
    monkeypatch.syspath_prepend(str(APP))
    at = AppTest.from_file(str(script), default_timeout=180)
    at.session_state["p_source"] = SYNTH
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def texts(at: AppTest) -> str:
    """Everything a user can read on the page, as one string."""
    groups = (at.markdown, at.caption, at.error, at.warning, at.info, at.success)
    return " ".join(str(e.value) for group in groups for e in group)


def metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def scripted_live(tmp_path, monkeypatch, published=None, when="2026-11-12 17:00"):
    """Wire the dashboard's Yahoo source to an offline scripted provider and clock."""
    import components.common as common

    from fixtures.live import CALENDAR, Clock, ScriptedYahoo, sessions
    from quantlab.data import LiveDataStore

    clock = Clock(when)
    history = sessions("2023-01-03", "2026-11-12")
    provider = ScriptedYahoo(clock, published or {"AAA": list(history), "BBB": list(history)})
    store = LiveDataStore(provider, tmp_path, CALENDAR, clock)
    monkeypatch.setattr(common, "live_store", lambda: store)
    return clock, provider, store


LIVE_STATE = {"p_source": LIVE, "p_tick": "AAA, BBB", "p_start": date(2023, 1, 1)}
