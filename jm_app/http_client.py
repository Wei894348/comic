import random
import threading
from typing import Optional
from urllib.parse import urlparse

import requests

from .constants import BASE_URL, DEFAULT_USER_AGENT
from .cookie_store import load_cookie_header, save_cookie_dict
from .jmcomic_defaults import jmcomic_default_cookie_header
from .models import NetworkConfig
from .utils import looks_like_security_page, parse_cookie_header


class HttpClient:
    def __init__(self, config: NetworkConfig, log_callback=None, cancel_event=None):
        self.config = config
        self.log_callback = log_callback
        self.cancel_event = cancel_event or threading.Event()
        self.last_url = ""
        self.session = requests.Session()
        self.session.trust_env = False
        self.cookie_source = "user" if config.cookie_header.strip() else ""
        cookie_header = config.cookie_header.strip()
        if not cookie_header:
            cookie_header = load_cookie_header()
            self.cookie_source = "requests-session" if cookie_header else ""
        if not cookie_header:
            cookie_header = jmcomic_default_cookie_header()
            self.cookie_source = "jmcomic-default" if cookie_header else "none"

        self.session.headers.update(
            {
                "User-Agent": config.user_agent or DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Referer": BASE_URL + "/",
            }
        )
        if config.proxy.strip():
            proxy = config.proxy.strip()
            self.session.proxies.update({"http": proxy, "https": proxy})
            self.log(f"已启用代理：{proxy}")
        if cookie_header:
            if self.cookie_source == "requests-session":
                self.log("已使用本地 requests Session Cookie。")
            elif self.cookie_source == "jmcomic-default":
                self.log("已使用 jmcomic 默认 Cookie。")
        else:
            self.log("当前没有可用 Cookie；requests 会尝试从站点响应中自动获取并保存 Cookie。")

        for name, value in parse_cookie_header(cookie_header).items():
            self.session.cookies.set(name, value, domain=urlparse(BASE_URL).netloc, path="/")

    def save_session_cookies(self):
        cookies = self.session.cookies.get_dict(domain=urlparse(BASE_URL).netloc)
        if not cookies:
            cookies = self.session.cookies.get_dict()
        if cookies:
            save_cookie_dict(cookies)
            if self.cookie_source == "none":
                self.cookie_source = "requests-session"

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def get_text(self, url: str) -> str:
        response = self.request("GET", url)
        response.encoding = response.apparent_encoding or response.encoding
        text = response.text
        if looks_like_security_page(text):
            raise RuntimeError(self.security_page_message(response.url, response.status_code))
        return text

    def security_page_message(self, url: str, status_code: int) -> str:
        base = f"站点返回安全验证页（HTTP {status_code}，最终地址：{url}）。"
        if self.cookie_source == "none":
            return base + "当前请求没有携带 Cookie；请在系统浏览器完成验证后粘贴该站点 Cookie。"
        if self.cookie_source == "jmcomic-default":
            return (
                base
                + "已尝试使用 jmcomic 默认 Cookie，但它不存在、已失效，或不适用于当前网页域名；"
                "请改用系统浏览器验证后的 Cookie。"
            )
        if self.cookie_source == "requests-session":
            return (
                base
                + "已尝试使用 requests 自动保存的 Session Cookie，但仍未通过验证；"
                "如果站点要求 JS/人工验证，requests 无法自动完成该验证。"
            )
        return (
            base
            + "已携带你填写的 Cookie 但仍未通过验证；请确认 Cookie 来自同一域名、未过期，"
            "并且 User-Agent 与复制 Cookie 的浏览器一致。"
        )

    def request(self, method: str, url: str, **kwargs):
        last_error: Optional[Exception] = None
        for attempt in range(1, self.config.retries + 2):
            if self.cancel_event.is_set():
                raise RuntimeError("任务已取消")
            try:
                response = self.session.request(method, url, timeout=45, **kwargs)
                self.save_session_cookies()
                if response.status_code in {403, 429}:
                    message = f"HTTP {response.status_code}: {url}"
                    if self.config.stop_on_block:
                        raise RuntimeError(message + "；站点拒绝或限流，请暂停后再试。")
                    raise requests.HTTPError(message, response=response)
                response.raise_for_status()
                self.last_url = response.url
                self.save_session_cookies()
                return response
            except Exception as exc:
                last_error = exc
                if attempt > self.config.retries:
                    break
                wait = self.config.backoff_seconds * attempt + random.uniform(0.5, 2.5)
                self.log(f"请求失败，{wait:.1f}s 后重试：{exc}")
                self.cancel_event.wait(wait)
        raise RuntimeError(str(last_error))

    def sleep(self):
        low = min(self.config.delay_min, self.config.delay_max)
        high = max(self.config.delay_min, self.config.delay_max)
        self.cancel_event.wait(random.uniform(low, high))
