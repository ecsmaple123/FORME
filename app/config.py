"""Settings: environment variables override values in .env (KEY=VALUE lines)."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"  # free tier; GEMINI_MODEL in .env picks another


def _read_env_file(path: Path) -> dict:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    backup_dir: Path
    backup_keep: int
    max_upload_mb: int
    gemini_api_key: str
    gemini_model: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wardrobe.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.staging_dir, self.tmp_dir, self.backup_dir):
            d.mkdir(parents=True, exist_ok=True)
        for kind in ("orig", "display", "thumb", "cutout"):
            (self.images_dir / kind).mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    env = _read_env_file(PROJECT_DIR / ".env")
    env.update(os.environ)
    return Settings(
        host=env.get("WARDROBE_HOST", "192.168.0.129"),
        port=int(env.get("WARDROBE_PORT", "8484")),
        data_dir=Path(env.get("WARDROBE_DATA", PROJECT_DIR / "data")),
        backup_dir=Path(env.get("WARDROBE_BACKUPS", PROJECT_DIR / "backups")),
        backup_keep=int(env.get("WARDROBE_BACKUP_KEEP", "7")),
        max_upload_mb=int(env.get("WARDROBE_MAX_UPLOAD_MB", "20")),
        gemini_api_key=env.get("GEMINI_API_KEY", ""),
        gemini_model=env.get("GEMINI_MODEL", "") or DEFAULT_GEMINI_MODEL,
    )
