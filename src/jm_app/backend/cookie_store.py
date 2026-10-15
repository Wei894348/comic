import json
from typing import Dict

from .credential_store import delete_secret, get_secret, set_secret
from .runtime_paths import cookie_file_path

COOKIE_FILE = cookie_file_path()
_COOKIE_SECRET = "session_cookies"


def cookie_dict_to_header(cookies: Dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items() if name)


def load_cookie_dict() -> Dict[str, str]:
    protected = get_secret(_COOKIE_SECRET)
    if protected:
        try:
            data = json.loads(protected)
        except (ValueError, TypeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            try:
                COOKIE_FILE.unlink(missing_ok=True)
            except OSError:
                pass
            return {str(name): str(value) for name, value in data.items() if name}

    # Compatibility with releases that wrote session/cookies.json in plaintext.
    try:
        data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    cookies = {str(name): str(value) for name, value in data.items() if name}
    if cookies:
        try:
            set_secret(_COOKIE_SECRET, json.dumps(cookies, ensure_ascii=False))
        except (OSError, RuntimeError):
            return cookies
        COOKIE_FILE.unlink(missing_ok=True)
    return cookies


def load_cookie_header() -> str:
    return cookie_dict_to_header(load_cookie_dict())


def save_cookie_dict(cookies: Dict[str, str]) -> None:
    cookies = {str(name): str(value) for name, value in cookies.items() if name and value}
    if not cookies:
        return
    set_secret(_COOKIE_SECRET, json.dumps(cookies, ensure_ascii=False))
    COOKIE_FILE.unlink(missing_ok=True)


def clear_cookie_store() -> None:
    """Remove persisted authentication cookies when the user signs out."""
    try:
        delete_secret(_COOKIE_SECRET)
    except OSError:
        pass
    try:
        COOKIE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
