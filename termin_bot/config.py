"""Einstellungen aus Umgebungsvariablen bzw. einer .env-Datei."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    bot_token: str
    admin_ids: set[int]
    salon_file: Path
    database: Path
    dashboard_token: str
    review_url: str
    web_host: str
    web_port: int

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()
        salon = Path(os.getenv("SALON_FILE", "salon.yaml"))
        if not salon.exists():
            salon = Path("salon.example.yaml")
        return cls(
            bot_token=os.getenv("BOT_TOKEN", ""),
            admin_ids={int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x},
            salon_file=salon,
            database=Path(os.getenv("DATABASE", "data/termine.db")),
            dashboard_token=os.getenv("DASHBOARD_TOKEN", ""),
            review_url=os.getenv("REVIEW_URL", ""),
            web_host=os.getenv("WEB_HOST", "127.0.0.1"),
            web_port=int(os.getenv("WEB_PORT", "8080")),
        )
