# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Lifecycle tracking for account-manager background workers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class WorkerRegistry:
    """Keep workers alive and coordinate a bounded, cooperative shutdown.

    Workers opt into critical shutdown handling with ``shutdown_critical = True``.
    Critical workers are operations that must reach a safe boundary before the
    process exits; cancellable workers may be left behind after the timeout.
    """

    def __init__(self) -> None:
        self._workers: dict[int, Any] = {}

    def track(self, worker: Any) -> None:
        key = id(worker)
        self._workers[key] = worker
        completion = getattr(worker, "shutdown_finished", worker.finished)
        completion.connect(lambda *_, key=key: self._workers.pop(key, None))

    def _running(self, *, critical_only: bool = False) -> list[Any]:
        running: list[Any] = []
        for worker in tuple(self._workers.values()):
            if critical_only and not bool(
                getattr(worker, "shutdown_critical", False)
            ):
                continue
            try:
                if worker.isRunning():
                    running.append(worker)
                else:
                    self._workers.pop(id(worker), None)
            except RuntimeError:
                # A Qt object can be deleted before its queued ``finished``
                # callback is delivered. Treat it as no longer live.
                self._workers.pop(id(worker), None)
        return running

    def any_running(self, *, critical_only: bool = False) -> bool:
        return bool(self._running(critical_only=critical_only))

    def running_names(self, *, critical_only: bool = False) -> list[str]:
        return [
            getattr(worker, "shutdown_name", type(worker).__name__)
            for worker in self._running(critical_only=critical_only)
        ]

    def critical_descriptions(self) -> list[str]:
        return [
            getattr(worker, "shutdown_description", type(worker).__name__)
            for worker in self._running(critical_only=True)
        ]

    def request_interruption(self, *, critical_only: bool = False) -> None:
        for worker in self._running(critical_only=critical_only):
            worker.requestInterruption()

    @staticmethod
    def _stop(workers: Iterable[Any]) -> None:
        for worker in workers:
            worker.requestInterruption()
            worker.quit()

    def shutdown(self, timeout_ms: int = 10_000) -> bool:
        workers = self._running()
        self._stop(workers)
        stopped = True
        for worker in workers:
            if not worker.wait(timeout_ms):
                stopped = False
        return stopped
