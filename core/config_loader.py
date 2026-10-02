import json
from pathlib import Path
from core.db import DB

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
TEXTS_PATH = PROJECT_ROOT / "config" / "texts.json"

def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)

# Initial
CFG = _load_json(CONFIG_PATH)
TEXTS = _load_json(TEXTS_PATH)
DBH = DB(str((PROJECT_ROOT / CFG["DB_PATH"]).resolve()))

def reload_config():
    global CFG
    new_cfg = _load_json(CONFIG_PATH)
    CFG.clear()
    CFG.update(new_cfg)
    DBH.path = str((PROJECT_ROOT / CFG["DB_PATH"]).resolve())
    DBH._init_db()
    return CFG

def reload_texts():
    global TEXTS
    new_texts = _load_json(TEXTS_PATH)
    TEXTS.clear()
    TEXTS.update(new_texts)
    return TEXTS
