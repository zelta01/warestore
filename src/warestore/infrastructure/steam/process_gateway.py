# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

import logging
import os
import subprocess
import sys
import time

import psutil

logger = logging.getLogger(__name__)

# Prevent console windows from flashing on screen when spawning child processes.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW


class SteamStillRunningError(RuntimeError):
    """Steam survived every graceful and forced termination attempt."""


class SteamProcessGateway:
    _PROCESSES = (
        "steam.exe",
        "steamservice.exe",
        "steamwebhelper.exe",
        "steamerrorreporter.exe",
        "streaming_client.exe",
    )

    @staticmethod
    def _named_processes(names: tuple[str, ...]) -> list[psutil.Process]:
        wanted = {name.casefold() for name in names}
        found: list[psutil.Process] = []
        for process in psutil.process_iter(["name"]):
            try:
                name = process.info.get("name") or ""
                if name.casefold() in wanted:
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return found

    @classmethod
    def _wait_until_gone(
        cls, names: tuple[str, ...], timeout: float
    ) -> list[psutil.Process]:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            survivors = cls._named_processes(names)
            if not survivors or time.monotonic() >= deadline:
                return survivors
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    @classmethod
    def _wait_until_present(cls, names: tuple[str, ...], timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if cls._named_processes(names):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    @staticmethod
    def _force_kill(processes: list[psutil.Process]) -> None:
        for process in processes:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def kill(self, *, timeout: float = 10.0) -> None:
        logger.info("Killing Steam processes...")
        for proc in self._PROCESSES:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        survivors = self._wait_until_gone(self._PROCESSES, timeout)
        if not survivors:
            return

        logger.warning(
            "Steam processes survived taskkill; escalating to psutil.Process.kill(): %s",
            ", ".join(sorted({proc.info.get("name") or str(proc.pid) for proc in survivors})),
        )
        self._force_kill(survivors)
        survivors = self._wait_until_gone(
            self._PROCESSES, min(2.0, max(0.0, timeout))
        )
        if survivors:
            names = sorted({proc.info.get("name") or str(proc.pid) for proc in survivors})
            raise SteamStillRunningError(
                "Steam did not exit after forced termination: " + ", ".join(names)
            )

    def install_path(self) -> str | None:
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            path, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
            return path.replace("/", "\\")
        except OSError:
            return None

    def local_vdf_path(self) -> str:
        return os.path.join(os.getenv("LOCALAPPDATA", ""), "Steam", "local.vdf")

    def launch(self, *, open_cs2: bool = False) -> None:
        steam_dir = self.install_path()
        steam_exe = os.path.join(steam_dir, "steam.exe") if steam_dir else None
        if steam_exe and os.path.exists(steam_exe):
            args = [steam_exe]
            if open_cs2:
                args += ["-applaunch", "730"]
            subprocess.Popen(args)
            logger.info(f'Steam launched{" → CS2 (730)" if open_cs2 else ""}.')
        else:
            url = "steam://rungameid/730" if open_cs2 else "steam://open/main"
            os.startfile(url)
            logger.info(f'Steam launched via protocol{" (CS2)" if open_cs2 else ""}.')

    def kill_injectors(self) -> None:
        # Each injector runs in wait-for-steam mode and never exits on its own,
        # so without this they pile up one-per-login (each with a cmd.exe child).
        # /T also clears those child processes.
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "injector.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
        survivors = self._wait_until_gone(("injector.exe",), 3.0)
        if survivors:
            self._force_kill(survivors)
            survivors = self._wait_until_gone(("injector.exe",), 1.0)
        if survivors:
            raise RuntimeError("A previous injector.exe process could not be stopped")

    def launch_with_spoofer(self, injector_path: str, *, open_cs2: bool = False) -> None:
        from warestore.infrastructure.steam.injector_stage import verify_injector

        try:
            verify_injector(
                injector_path,
                require_secure_dir=getattr(sys, "frozen", False),
            )
        except Exception as exc:
            logger.error(
                "Refusing to launch untrusted injector; falling back to normal Steam: %s",
                exc,
            )
            self.launch(open_cs2=open_cs2)
            return
        # Reap any leftover injectors from previous logins before spawning a new
        # one — only a single wait-for-steam watcher should ever be running.
        self.kill_injectors()
        # Injector kills any lingering steam.exe then waits for the next one.
        # Confirm the watcher process exists before Steam starts; otherwise
        # steam.exe can win the launch race.
        logger.info(f"Launching injector (wait-for-steam mode): {injector_path}")
        subprocess.Popen([injector_path], creationflags=_NO_WINDOW)
        if not self._wait_until_present(("injector.exe",), 5.0):
            raise RuntimeError("The HWID injector did not enter its watch loop")
        self.launch(open_cs2=open_cs2)
