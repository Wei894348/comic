"""Alibaba Cloud DashScope CosyVoice client."""

from __future__ import annotations

import os
import re
import socket
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from src.utils import desktop_pet_base

CONFIG_DIR = desktop_pet_base() / "config"
CONFIG_PATH = CONFIG_DIR / "cosyvoice.yaml"
LOCAL_CONFIG_PATH = CONFIG_DIR / "cosyvoice.local.yaml"
_DASHSCOPE_HOST = "dashscope.aliyuncs.com"
_DNS_OVERRIDE_LOCK = threading.Lock()
_NATURAL_DELIVERY = "按标点自然停顿，重点词轻微重读，句末语调自然变化，避免逐字匀速朗读。"
_PLAYFUL_INTIMACY = "保持俏皮、亲近、若有若无的含蓄暧昧感，但不要使用露骨表达。"


def _ensure_stdlib_platform() -> None:
    module = sys.modules.get("platform")
    if module is not None and hasattr(module, "python_implementation"):
        return

    src_dir = Path(__file__).resolve().parents[1]
    original_path = sys.path[:]
    original_module = module

    try:
        sys.modules.pop("platform", None)
        sys.path[:] = [
            path
            for path in original_path
            if _safe_resolve(path) != src_dir
        ]
        import platform as stdlib_platform

        if not hasattr(stdlib_platform, "python_implementation"):
            raise ImportError("stdlib platform module was shadowed")
        sys.modules["platform"] = stdlib_platform
    except Exception:
        if original_module is not None:
            sys.modules["platform"] = original_module
    finally:
        sys.path[:] = original_path


def _safe_resolve(path: str) -> Path | None:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return None


def _language_hints(text: str) -> list[str]:
    chinese_count = len(re.findall(r"[\u3400-\u9fff]", text))
    english_count = len(re.findall(r"[A-Za-z]", text))
    return ["zh"] if chinese_count >= english_count else ["en"]


def _speech_instruction(text: str) -> str:
    lowered = text.lower()
    if any(
        keyword in lowered
        for keyword in ("难过", "伤心", "累了", "害怕", "别哭", "抱抱", "安慰")
    ):
        return f"用温柔、关心、略带安慰的少女语气自然朗读，语速稍缓，情绪真诚。{_PLAYFUL_INTIMACY}{_NATURAL_DELIVERY}"
    if any(keyword in lowered for keyword in ("生气", "讨厌", "不许", "认真", "警告")):
        return f"用认真但不凶的少女语气朗读，重点词清晰，语调坚定。{_PLAYFUL_INTIMACY}{_NATURAL_DELIVERY}"
    if "?" in text or "？" in text:
        return f"用轻快、好奇、带一点俏皮感的少女语气朗读，语调自然上扬。{_PLAYFUL_INTIMACY}{_NATURAL_DELIVERY}"
    if "!" in text or "！" in text or any(
        keyword in lowered
        for keyword in ("开心", "太好了", "恭喜", "喜欢", "成功", "好耶")
    ):
        return f"用开心、元气、有感染力的少女语气朗读，语调有自然起伏，不要夸张。{_PLAYFUL_INTIMACY}{_NATURAL_DELIVERY}"
    return f"用自然、灵动、有亲和力的少女语气朗读，语调有轻微起伏，避免机械感。{_PLAYFUL_INTIMACY}{_NATURAL_DELIVERY}"


@contextmanager
def _dashscope_ipv4_only():
    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        addresses = original_getaddrinfo(host, *args, **kwargs)
        if str(host).lower() != _DASHSCOPE_HOST:
            return addresses

        ipv4_addresses = [
            address for address in addresses if address[0] == socket.AF_INET
        ]
        return ipv4_addresses or addresses

    with _DNS_OVERRIDE_LOCK:
        socket.getaddrinfo = getaddrinfo
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo


def _read_config_file(path: Path) -> dict[str, object]:
    try:
        import yaml

        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data.get("cosyvoice", {}) if isinstance(data, dict) else {}
    except (OSError, ImportError, ValueError):
        return {}


def _load_file_config() -> dict[str, object]:
    config = _read_config_file(CONFIG_PATH)
    config.update(_read_config_file(LOCAL_CONFIG_PATH))
    return config


def _read_setting(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value or os.name != "nt":
        return value or default

    # A GUI-launched process may not inherit a user variable created later.
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip() or default
    except (OSError, FileNotFoundError):
        return default


class CosyVoiceTTS:
    """Generate arbitrary text with a DashScope custom CosyVoice voice."""

    def __init__(self) -> None:
        config = _load_file_config()
        self.enabled = bool(config.get("enabled", True))
        self.api_key = _read_setting(
            "DASHSCOPE_API_KEY", str(config.get("api_key", ""))
        )
        self.voice_id = _read_setting(
            "COSYVOICE_VOICE_ID", str(config.get("voice_id", ""))
        )
        self.model = _read_setting(
            "COSYVOICE_MODEL",
            str(config.get("model", "cosyvoice-v3.5-plus")),
        )

    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key and self.voice_id)

    def synthesize(self, text: str) -> bytes:
        if not self.is_configured():
            raise RuntimeError("CosyVoice configuration is incomplete")

        _ensure_stdlib_platform()
        try:
            import dashscope
            from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
        except ImportError as exc:
            raise RuntimeError(
                f"DashScope 语音模块导入失败: {exc!r}"
            ) from exc

        dashscope.api_key = self.api_key
        synthesizer = SpeechSynthesizer(
            model=self.model,
            voice=self.voice_id,
            format=AudioFormat.MP3_24000HZ_MONO_256KBPS,
            language_hints=_language_hints(text),
            instruction=_speech_instruction(text),
            speech_rate=1.05,
        )
        with _dashscope_ipv4_only():
            audio = synthesizer.call(text)
        if not audio:
            response = synthesizer.get_response() or {}
            header = response.get("header", {})
            error_code = header.get("error_code", "UnknownError")
            error_message = header.get("error_message", "未返回音频数据")
            raise RuntimeError(f"CosyVoice {error_code}: {error_message}")
        return bytes(audio)
