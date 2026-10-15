"""配置管理模块"""

import json
from typing import Any, Dict, Optional
from src.constants import (
    AI_DEFAULT_MODELS,
    AI_PROVIDER_DEEPSEEK,
    CONFIG_FILE,
    LEGACY_CONFIG_FILE,
    DEFAULT_SCALE_INDEX,
    DEFAULT_TRANSPARENCY_INDEX,
    DEFAULT_TRANSLATE_LANG,
    TRANSLATE_LANGUAGES,
)
from src.credential_store import load_secret, save_secret
from src.atomic_write import atomic_write_json


_AI_API_KEY_SECRET = "ai_api_key"

# 配置缓存
_config_cache: Optional[Dict[str, Any]] = None


def _default_config() -> Dict[str, Any]:
    """返回默认配置"""
    return {
        "scale_index": DEFAULT_SCALE_INDEX,
        "transparency_index": DEFAULT_TRANSPARENCY_INDEX,
        "auto_startup": False,
        "click_through": False,
        "follow_mouse": False,
        "behavior_mode": "active",
        # AI配置
        "ai_enabled": False,
        "ai_provider": AI_PROVIDER_DEEPSEEK,
        "ai_api_key": "",
        "ai_model": AI_DEFAULT_MODELS[AI_PROVIDER_DEEPSEEK],
        "ai_base_url": "",
        "ai_personality": "aemeath",
        # 翻译配置
        "translate_enabled": False,
        "translate_target_lang": DEFAULT_TRANSLATE_LANG,
        # 快速启动配置
        "quick_launch_enabled": False,
        "quick_launch_exe_path": "",
        "quick_launch_click_count": 5,
    }


def load_config(force_refresh: bool = False) -> Dict[str, Any]:
    """加载配置，使用缓存减少IO

    Args:
        force_refresh: 是否强制刷新缓存

    Returns:
        配置字典
    """
    global _config_cache

    if not force_refresh and _config_cache is not None:
        return _config_cache.copy()

    source_path = CONFIG_FILE if CONFIG_FILE.exists() else LEGACY_CONFIG_FILE
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"配置文件不存在，使用默认配置")
        data = _default_config()
    except json.JSONDecodeError as e:
        print(f"配置文件损坏 ({e})，使用默认配置")
        data = _default_config()

    legacy_api_key = str(data.pop("ai_api_key", "") or "")
    api_key = load_secret(_AI_API_KEY_SECRET)
    if not api_key and legacy_api_key:
        if save_secret(_AI_API_KEY_SECRET, legacy_api_key):
            api_key = legacy_api_key
            try:
                atomic_write_json(CONFIG_FILE, data, indent=2)
                if source_path == LEGACY_CONFIG_FILE:
                    atomic_write_json(source_path, data, indent=2)
            except OSError:
                pass
        else:
            # Keep the legacy value usable in memory if DPAPI is temporarily
            # unavailable; do not rewrite the plaintext file in this case.
            api_key = legacy_api_key
    elif source_path == LEGACY_CONFIG_FILE and source_path.exists():
        try:
            atomic_write_json(CONFIG_FILE, data, indent=2)
        except OSError:
            pass
    data["ai_api_key"] = api_key
    _config_cache = data.copy()
    return data


def save_config(config: Dict[str, Any]) -> None:
    """保存配置到文件

    Args:
        config: 配置字典
    """
    global _config_cache

    try:
        runtime_config = config.copy()
        api_key = str(runtime_config.pop("ai_api_key", "") or "")
        if not save_secret(_AI_API_KEY_SECRET, api_key):
            raise OSError("Windows DPAPI 凭据保存失败")
        atomic_write_json(CONFIG_FILE, runtime_config, indent=2)
        _config_cache = config.copy()
    except (OSError, IOError) as e:
        print(f"保存配置失败: {e}")


def update_config(**kwargs) -> Dict[str, Any]:
    """更新配置并保存

    Args:
        **kwargs: 要更新的配置项

    Returns:
        更新后的配置字典
    """
    config = load_config()
    config.update(kwargs)
    save_config(config)
    return config.copy()


def get_config_value(key: str, default=None) -> Any:
    """获取单个配置值

    Args:
        key: 配置键名
        default: 默认值

    Returns:
        配置值
    """
    config = load_config()
    return config.get(key, default)
