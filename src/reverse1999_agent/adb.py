from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image


class AdbError(RuntimeError):
    pass


class AdbClient:
    def __init__(self, executable: Path, serial: str) -> None:
        self.executable = executable
        self.serial = serial

    def _base(self, *, serial: bool = True) -> list[str]:
        command = [str(self.executable)]
        if serial:
            command.extend(["-s", self.serial])
        return command

    def _run(self, *args: str, binary: bool = False, timeout: float = 30) -> bytes | str:
        command = [*self._base(), *args]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise AdbError(f"ADB failed ({result.returncode}): {stderr}")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace").strip()

    def connect(self) -> str:
        if not self.executable.exists() and shutil.which(str(self.executable)) is None:
            raise AdbError(f"ADB executable not found: {self.executable}")
        result = subprocess.run(
            [str(self.executable), "connect", self.serial],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise AdbError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    def device_state(self) -> str:
        return str(self._run("get-state", timeout=10))

    def screenshot(self) -> Image.Image:
        payload = self._run("exec-out", "screencap", "-p", binary=True, timeout=20)
        assert isinstance(payload, bytes)
        try:
            image = Image.open(io.BytesIO(payload))
            image.load()
            return image.convert("RGB")
        except Exception as exc:
            raise AdbError("MuMu returned an invalid screenshot") from exc

    def tap(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 350) -> None:
        self._run(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        )

    def back(self) -> None:
        self._run("shell", "input", "keyevent", "4")
