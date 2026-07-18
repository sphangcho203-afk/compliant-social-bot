from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BOT_", extra="ignore")

    db_path: Path = Path("./data/bot.db")
    media_dir: Path = Path("./data/media")
    render_dir: Path = Path("./data/rendered")
    log_level: str = "INFO"
    dry_run: bool = True
    min_post_hours: int = 48
    max_post_hours: int = 72

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.render_dir.mkdir(parents=True, exist_ok=True)
