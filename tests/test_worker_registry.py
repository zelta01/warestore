from warestore.presentation.account_manager.support.worker_registry import WorkerRegistry


class FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()


class FakeWorker:
    shutdown_critical = True

    def __init__(self, name: str, *, wait_result: bool = True) -> None:
        self.shutdown_name = name
        self.finished = FakeSignal()
        self.running = True
        self.wait_result = wait_result
        self.interruptions = 0
        self.quits = 0
        self.waits = []

    def isRunning(self) -> bool:
        return self.running

    def requestInterruption(self) -> None:
        self.interruptions += 1

    def quit(self) -> None:
        self.quits += 1

    def wait(self, timeout_ms: int) -> bool:
        self.waits.append(timeout_ms)
        if self.wait_result:
            self.running = False
        return self.wait_result


def test_track_drops_worker_after_finished() -> None:
    registry = WorkerRegistry()
    worker = FakeWorker("status")
    registry.track(worker)

    assert registry.any_running()
    worker.running = False
    worker.finished.emit()

    assert not registry.any_running()
    assert registry.running_names() == []


def test_running_queries_reflect_only_live_workers() -> None:
    registry = WorkerRegistry()
    live = FakeWorker("live")
    stopped = FakeWorker("stopped")
    stopped.running = False
    registry.track(live)
    registry.track(stopped)

    assert registry.any_running()
    assert registry.running_names() == ["live"]


def test_shutdown_waits_for_critical_worker_and_succeeds() -> None:
    registry = WorkerRegistry()
    worker = FakeWorker("SwitchWorker")
    registry.track(worker)

    assert registry.shutdown(timeout_ms=1234) is True
    assert worker.interruptions == 1
    assert worker.quits == 1
    assert worker.waits == [1234]


def test_shutdown_reports_refusing_worker_by_name() -> None:
    registry = WorkerRegistry()
    worker = FakeWorker("UserdataDeleteWorker", wait_result=False)
    registry.track(worker)

    assert registry.shutdown(timeout_ms=25) is False
    assert registry.running_names() == ["UserdataDeleteWorker"]
