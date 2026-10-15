from typing import Dict


def normalize_cookie_header(cookies) -> str:
    if not cookies:
        return ""
    if isinstance(cookies, str):
        return cookies.strip()
    if isinstance(cookies, Dict):
        return "; ".join(f"{key}={value}" for key, value in cookies.items() if key)
    return ""


def jmcomic_default_cookie_header() -> str:
    try:
        from jmcomic import JmModuleConfig, JmOption
    except Exception:
        return ""

    candidates = [
        getattr(JmModuleConfig, "APP_COOKIES", None),
    ]

    try:
        option = JmOption.default()
        meta = option.client.postman.meta_data.src_dict
        candidates.append(meta.get("cookies"))
    except Exception:
        pass

    for cookies in candidates:
        header = normalize_cookie_header(cookies)
        if header:
            return header
    return ""
