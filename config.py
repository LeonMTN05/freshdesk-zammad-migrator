"""Konfiguration: Laden/Speichern von config.json sowie zentrale Pfade und Konstanten."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "migration_state.json"
FAILED_FILE = BASE_DIR / "failed_records.json"
LOG_FILE = BASE_DIR / "migration.log"

# Freshdesk-Standard-IDs laut API-Dokumentation
FD_STATUS_NAMES = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
FD_PRIORITY_NAMES = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}

# Vorbelegung des Mappings (Freshdesk-ID -> Zammad-Name, wird in der GUI aufgelöst)
DEFAULT_STATUS_MAP = {2: "open", 3: "pending reminder", 4: "closed", 5: "closed"}
DEFAULT_PRIORITY_MAP = {1: "1 low", 2: "2 normal", 3: "3 high", 4: "3 high"}

DEFAULT_CONFIG = {
    "freshdesk_subdomain": "",
    "freshdesk_api_key": "",
    "zammad_url": "",
    "zammad_token": "",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )
