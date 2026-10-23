"""Thread-safe callback dispatch for Tkinter applications.

Tk widgets may only be touched from the thread that created them. Background
workers therefore must not call ``widget.after`` directly. They enqueue a
callback here instead, and a timer owned by the main thread drains the queue.
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

logger = logging.getLogger(__name__)

Callback = Callable[[], None]


class WidgetLike(Protocol):
    """The small part of the Tk widget API needed by the dispatcher."""

    def after(self, delay_ms: int, callback: Callable[[], object]) -> str: ...

    def after_cancel(self, callback_id: str) -> None: ...

    def winfo_exists(self) -> int: ...


class TkDispatcher:
    """Schedule callbacks from worker threads onto Tk's main thread.

    ``post`` intentionally mirrors the ``(delay_ms, callback)`` signature of
    ``widget.after`` so it can be passed to services such as ``ImageLoader``.
    The delay is ignored: queued work runs on the next timer tick.

    The dispatcher must be created on the main thread. It keeps a lightweight
    timer running while the widget exists; ``close`` stops it explicitly.
    """

    def __init__(self, widget: WidgetLike, interval_ms: int = 50) -> None:
        self._widget = widget
        self._interval_ms = max(10, int(interval_ms))
        self._queue: queue.Queue[Callback] = queue.Queue()
        self._after_id: str | None = None
        self._closed = False
        self._schedule()

    @property
    def closed(self) -> bool:
        return self._closed

    def post(self, _delay_ms: int, callback: Callback) -> None:
        """Queue a callback. Safe to call from any thread."""
        if self._closed:
            return
        self._queue.put(callback)

    def close(self) -> None:
        """Stop the timer and drop pending callbacks."""
        self._closed = True
        if self._after_id is not None:
            with suppress(tk.TclError):
                self._widget.after_cancel(self._after_id)
            self._after_id = None

        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _schedule(self) -> None:
        if self._closed or not self._widget_alive():
            return
        try:
            self._after_id = self._widget.after(self._interval_ms, self._drain)
        except tk.TclError:
            self._closed = True

    def _drain(self) -> None:
        self._after_id = None
        if self._closed:
            return
        if not self._widget_alive():
            self._closed = True
            return

        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                break

            try:
                callback()
            except Exception:
                logger.exception("Tk callback failed")

        self._schedule()

    def _widget_alive(self) -> bool:
        try:
            return bool(self._widget.winfo_exists())
        except tk.TclError:
            return False
