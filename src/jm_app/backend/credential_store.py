"""Per-user DPAPI-backed storage for credentials excluded from JSON settings."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
from typing import Dict

from .atomic_write import atomic_write_json, exclusive_path_lock
from .runtime_paths import app_data_dir


_FILE_NAME = "credentials.json"
_DESCRIPTION = "comic18 credential"


def _credentials_path() -> Path:
    return app_data_dir() / _FILE_NAME


def _load_entries() -> Dict[str, str]:
    path = _credentials_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(name): str(value) for name, value in data.items() if str(name)}


def _protect(value: str) -> str:
    encrypted = _dpapi_protect(value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect(value: str) -> str:
    encrypted = base64.b64decode(value.encode("ascii"), validate=True)
    return _dpapi_unprotect(encrypted).decode("utf-8")


def _dpapi_protect(value: bytes) -> bytes:
    return _call_dpapi("CryptProtectData", value, _DESCRIPTION)


def _dpapi_unprotect(value: bytes) -> bytes:
    return _call_dpapi("CryptUnprotectData", value, None)


def _call_dpapi(function_name: str, value: bytes, description: str | None) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows credential protection is unavailable")
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = getattr(crypt32, function_name)
    function.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR if function_name == "CryptProtectData" else ctypes.c_void_p,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source_buffer = ctypes.create_string_buffer(value)
    source = DataBlob(
        len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte))
    )
    destination = DataBlob()
    description_arg = description if function_name == "CryptProtectData" else None
    if not function(
        ctypes.byref(source),
        description_arg,
        None,
        None,
        None,
        0,
        ctypes.byref(destination),
    ):
        raise OSError(ctypes.get_last_error(), f"{function_name} failed")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        kernel32.LocalFree(destination.pbData)


def get_secret(name: str) -> str:
    token = _load_entries().get(str(name), "")
    if not token:
        return ""
    try:
        return _unprotect(token)
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError):
        return ""


def set_secret(name: str, value: str) -> None:
    key = str(name).strip()
    if not key:
        raise ValueError("credential name cannot be empty")
    path = _credentials_path()
    with exclusive_path_lock(path):
        entries = _load_entries()
        if value:
            entries[key] = _protect(str(value))
        else:
            entries.pop(key, None)
        atomic_write_json(path, entries, indent=2)


def delete_secret(name: str) -> None:
    set_secret(name, "")


def migrate_legacy_base64_secret(name: str, encoded_value: str) -> str:
    """Import an old base64-only setting once, then return the protected value."""
    try:
        decoded = base64.b64decode(str(encoded_value).encode("ascii"), validate=True)
        value = decoded.decode("utf-8")
    except (UnicodeError, ValueError, TypeError):
        return ""
    if not value:
        return ""
    try:
        set_secret(name, value)
    except RuntimeError:
        return ""
    return value
