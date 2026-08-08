from warestore.infrastructure.steam.process_gateway import SteamStillRunningError
from warestore.presentation.account_manager.features.login.switch_worker import SwitchWorker
from warestore.presentation.account_manager.support.worker_registry import WorkerRegistry


class Controller:
    def __init__(self) -> None:
        self.login_calls = 0

    def kill_steam(self) -> None:
        raise SteamStillRunningError("steam.exe survived")

    def perform_token_login(self, *_args) -> bool:
        self.login_calls += 1
        return True


def test_switch_stops_before_login_when_steam_will_not_exit() -> None:
    controller = Controller()
    worker = SwitchWorker("token", token="token", ctrl=controller)
    results = []
    worker.finished.connect(results.append)

    worker.run()

    assert controller.login_calls == 0
    assert results == [False]
    assert "still running" in worker.error_message


def test_registry_can_track_switch_workers_with_custom_result_signal() -> None:
    registry = WorkerRegistry()
    worker = SwitchWorker("token", token="token", ctrl=Controller())

    registry.track(worker)

    assert registry.running_names() == []
