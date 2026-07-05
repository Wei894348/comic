import json
from pathlib import Path
from typing import Dict


COOKIE_FILE = Path.cwd() / ".session" / "cookies.json"


def cookie_dict_to_header(cookies: Dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if name)


def load_cookie_dict() -> Dict[str, str]:
    if not COOKIE_FILE.exists():
        return {}
    try:
        data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name): str(value) for name, value in data.items() if name}


def load_cookie_header() -> str:
    return cookie_dict_to_header(load_cookie_dict())


def save_cookie_dict(cookies: Dict[str, str]):
    cookies = {str(name): str(value) for name, value in cookies.items() if name and value}
    if not cookies:
        return
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
