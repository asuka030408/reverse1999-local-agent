from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="R1999_",
        extra="ignore",
    )

    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    adb_path: Path = Path("adb")
    adb_serial: str = "127.0.0.1:16384"
    dry_run: bool = True
    enable_ocr: bool = True
    step_delay_seconds: float = Field(default=2.0, ge=0.2, le=30.0)
    max_steps: int = Field(default=100, ge=1, le=10000)
    artifact_dir: Path = Path("artifacts")

    def ensure_dirs(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)
