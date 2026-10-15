from pydantic import BaseModel


class NetworkSettings(BaseModel):
    cookie_header: str = ""
    user_agent: str = ""
    delay_min: float = 1.0
    delay_max: float = 3.0
    retries: int = 3
    backoff_seconds: int = 3
    stop_on_block: bool = True
    username: str = ""
    password: str = ""
    proxy: str = ""
    detail_threads: int = 6
    save_password: bool = False
    auto_login: bool = False
    auto_sign: bool = False
    api_route: int = 0
    image_route: int = 0
    doh_enabled: bool = True
    doh_url: str = "https://parse.jpacg.cc/parse"
    custom_api_domain: str = ""
    custom_image_domain: str = ""
