import os
from pathlib import Path
from typing import Dict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
PROJECTS_DIR = DATA_DIR / "projects"
EXPORTS_DIR = DATA_DIR / "exports"
ASSETS_DIR = DATA_DIR / "assets"
BROLL_DIR = DATA_DIR / "broll"
SFX_DIR = DATA_DIR / "sfx"
ENV_FILE = ROOT_DIR / ".env.local"
DB_PATH = DATA_DIR / "oclip.db"

for d in [DATA_DIR, UPLOADS_DIR, PROJECTS_DIR, EXPORTS_DIR, ASSETS_DIR, BROLL_DIR, SFX_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def load_env_file() -> Dict[str, str]:
    vals: Dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            vals[k] = v
            if k not in os.environ or not os.environ[k]:
                os.environ[k] = v
    return vals


def save_env_keys(updates: Dict[str, str]) -> None:
    existing = load_env_file()
    for k, v in updates.items():
        if v is None:
            continue
        v_clean = v.strip()
        if v_clean:
            existing[k] = v_clean
            os.environ[k] = v_clean
        else:
            existing.pop(k, None)
            os.environ.pop(k, None)
    lines = ["# OClip local API keys (auto-managed)"]
    for k, v in sorted(existing.items()):
        lines.append(f'{k}="{v}"')
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_key(name: str) -> str:
    load_env_file()
    return os.environ.get(name, "").strip()


load_env_file()
