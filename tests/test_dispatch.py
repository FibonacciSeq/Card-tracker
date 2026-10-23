"""Tests for the worker-thread -> Tk main-thread dispatcher."""

from __future__ import annotations

import threading
from collections.abc import Callable

from ui.dispatch import TkDispatcher


class FakeWidget:
    """Minimal Tk widget double; no display or main loop required."""

    def __init__(self) -> None:
        self._callbacks: dict[str, tuple[int, Callable[[], object]]] = {}
        self._next_id = 0
        self.exists = True

    def after(self, delay_ms: int, callback: Callable[[], object]) -> str:
        self._next_id += 1
        callback_id = f"after-{self._next_id}"
        self._callbacks[callback_id] = (delay_ms, callback)
        return callback_id

    def after_cancel(self, callback_id: str) -> None:
        self._callbacks.pop(callback_id, None)

    def winfo_exists(self) -> bool:
        return self.exists

    def run_next(self) -> str:
        callback_id, (_delay, callback) = next(iter(self._callbacks.items()))
        self._callbacks.pop(callback_id)
        callback()
        return callback_id


def test_post_runs_callbacks_on_a_later_tick():
    widget = FakeWidget()
    dispatcher = TkDispatcher(widget, interval_ms=10)
    calls: list[str] = []

    dispatcher.post(0, lambda: calls.append("first"))
    dispatcher.post(0, lambda: calls.append("second"))

    assert calls == []
    widget.run_next()
    assert calls == ["first", "second"]

    dispatcher.close()
    assert widget._callbacks == {}


def test_post_from_a_worker_thread_is_queued_for_the_main_thread():
    widget = FakeWidget()
    dispatcher = TkDispatcher(widget)
    calls: list[str] = []
    posted = threading.Event()

    def worker():
        dispatcher.post(0, lambda: calls.append("from worker"))
        posted.set()

    thread = threading.Thread(target=worker)
    thread.start()
    assert posted.wait(timeout=5)
    thread.join(timeout=5)

    assert calls == []
    widget.run_next()
    assert calls == ["from worker"]
    dispatcher.close()


def test_close_drops_pending_callbacks():
    widget = FakeWidget()
    dispatcher = TkDispatcher(widget)
    calls: list[str] = []

    dispatcher.post(0, lambda: calls.append("late"))
    dispatcher.close()
    dispatcher.post(0, lambda: calls.append("ignored"))

    assert calls == []
    assert widget._callbacks == {}


def test_one_bad_callback_does_not_block_the_queue(caplog):
    widget = FakeWidget()
    dispatcher = TkDispatcher(widget)
    calls: list[str] = []

    def boom():
        raise RuntimeError("callback failed")

    dispatcher.post(0, boom)
    dispatcher.post(0, lambda: calls.append("survived"))

    with caplog.at_level("ERROR"):
        widget.run_next()

    assert calls == ["survived"]
    assert "Tk callback failed" in caplog.text
    dispatcher.close()


def test_destroyed_widget_stops_the_timer():
    widget = FakeWidget()
    dispatcher = TkDispatcher(widget)
    widget.exists = False

    widget.run_next()

    assert widget._callbacks == {}
    assert dispatcher.closed is True
