"""Temporary performance instrumentation for Pokestock.

This module is intentionally small and easy to remove after P3.
"""

from contextlib import contextmanager
import os
import time

import streamlit as st


PERF_ENV_VAR = "POKESTOCK_PERF"


def perf_enabled():
    return bool(st.session_state.get("perf_debug_enabled", False)) or os.getenv(PERF_ENV_VAR, "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def perf_reset_rerun():
    st.session_state["_perf_rerun"] = {
        "started_at": time.perf_counter(),
        "events": [],
        "counters": {},
    }


def _state():
    if "_perf_rerun" not in st.session_state:
        perf_reset_rerun()
    return st.session_state["_perf_rerun"]


def perf_count(name, amount=1):
    state = _state()
    counters = state.setdefault("counters", {})
    counters[name] = counters.get(name, 0) + amount


def perf_log(label, seconds=None, detail=""):
    if not perf_enabled():
        return
    if seconds is None:
        message = f"[PERF] {label}"
    else:
        message = f"[PERF] {label}: {seconds:.3f}s"
    if detail:
        message = f"{message} / {detail}"
    print(message)
    _state().setdefault("events", []).append(message)


@contextmanager
def perf_timer(label, counter=None, detail=None):
    if counter:
        perf_count(counter)
    start = time.perf_counter()
    try:
        yield
    finally:
        seconds = time.perf_counter() - start
        detail_text = detail() if callable(detail) else (detail or "")
        perf_log(label, seconds, detail_text)


def perf_summary():
    state = _state()
    elapsed = time.perf_counter() - state.get("started_at", time.perf_counter())
    counters = state.get("counters", {})
    if counters:
        counter_text = ", ".join(f"{key}={value}" for key, value in sorted(counters.items()))
    else:
        counter_text = "no counters"
    perf_log("rerun summary", elapsed, counter_text)
    return {
        "elapsed": elapsed,
        "counters": dict(counters),
        "events": list(state.get("events", [])),
    }
