from __future__ import annotations

import shutil
import subprocess
from typing import Any


def install_chiptune_policy(module: Any) -> None:
    if getattr(module, "_manageroo_chiptune_policy_installed", False):
        return

    def stop(self) -> None:
        process = self.process
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
            if self.temp_root:
                shutil.rmtree(self.temp_root, ignore_errors=True)
            self.path = None
            self.temp_root = None
            self.process = None

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
