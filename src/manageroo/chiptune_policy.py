from __future__ import annotations

import subprocess
from typing import Any


def install_chiptune_policy(module: Any) -> None:
    if getattr(module, "_manageroo_chiptune_policy_installed", False):
        return

    def stop(self) -> None:
        process = self._process
        temp_directory = self._temp_directory
        try:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=1.5)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
        finally:
            self._path = None
            self._temp_root = None
            self._temp_directory = None
            self._process = None
            if temp_directory:
                temp_directory.cleanup()

    def play_once(*, cue: str = "install", variant: int = 0) -> bool:
        playback = module.ThemePlayback(cue=module._validate_cue(cue), enabled=True, variant=variant)
        try:
            if not playback.start():
                return False
            if playback.process:
                playback.process.wait()
            return True
        finally:
            playback.stop()

    module.ThemePlayback.stop = stop
    module.play_once = play_once
    module._manageroo_chiptune_policy_installed = True
