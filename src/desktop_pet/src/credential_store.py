"""Windows DPAPI-backed secret storage for the desktop pet."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Dict

from .atomic_write import atomic_write_json, exclusive_path_lock


_ENTROPY = b"comic18.desktop-pet.credentials.v1"
_SECRET_FILE_NAME = "desktop_pet_credentials.json"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


_CRYPT32 = ctypes.WinDLL("crypt32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_CRYPT32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DataBlob),
    wintypes.LPCWSTR,
    ctypes.POINTER(_DataBlob),
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(_DataBlob),
]
_CRYPT32.CryptProtectData.restype = wintypes.BOOL
_CRYPT32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DataBlob),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(_DataBlob),
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(_DataBlob),
]
_CRYPT32.CryptUnprotectData.restype = wintypes.BOOL
_KERNEL32.LocalFree.argtypes = [wintypes.LPVOID]
_KERNEL32.LocalFree.restype = wintypes.LPVOID


def _input_blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _output_bytes(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _KERNEL32.LocalFree(ctypes.cast(blob.pbData, wintypes.LPVOID))


def credential_file() -> Path:
    override = os.environ.get("COMIC18_DATA_DIR", "").strip()
    if override:
        return Path(override) / _SECRET_FILE_NAME
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "comic18" / _SECRET_FILE_NAME


def _read_payload() -> Dict[str, str]:
    path = credential_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if key and value}


def _write_payload(payload: Dict[str, str]) -> None:
    path = credential_file()
    atomic_write_json(path, payload, indent=2)


def _protect(value: str) -> str:
    data_blob, data_buffer = _input_blob(value.encode("utf-8"))
    entropy_blob, entropy_buffer = _input_blob(_ENTROPY)
    output_blob = _DataBlob()
    success = _CRYPT32.CryptProtectData(
        ctypes.byref(data_blob),
        "comic18 desktop pet",
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del data_buffer, entropy_buffer
    if not success:
        raise ctypes.WinError()
    encrypted = _output_bytes(output_blob)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect(value: str) -> str:
    encrypted = base64.b64decode(value.encode("ascii"), validate=True)
    data_blob, data_buffer = _input_blob(encrypted)
    entropy_blob, entropy_buffer = _input_blob(_ENTROPY)
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    success = _CRYPT32.CryptUnprotectData(
        ctypes.byref(data_blob),
        ctypes.byref(description),
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del data_buffer, entropy_buffer
    if description:
        _KERNEL32.LocalFree(ctypes.cast(description, wintypes.LPVOID))
    if not success:
        raise ctypes.WinError()
    decrypted = _output_bytes(output_blob)
    return decrypted.decode("utf-8")


def load_secret(name: str) -> str:
    encrypted = _read_payload().get(str(name), "")
    if not encrypted:
        return ""
    try:
        return _unprotect(encrypted)
    except (OSError, ValueError, UnicodeError):
        return ""


def save_secret(name: str, value: str) -> bool:
    key = str(name).strip()
    if not key:
        return False
    try:
        path = credential_file()
        with exclusive_path_lock(path):
            payload = _read_payload()
            if value:
                payload[key] = _protect(str(value))
                _write_payload(payload)
            else:
                payload.pop(key, None)
                if payload:
                    _write_payload(payload)
                else:
                    path.unlink(missing_ok=True)
        return True
    except (OSError, ValueError):
        return False
