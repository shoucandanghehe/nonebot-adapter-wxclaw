from pydantic import BaseModel, Field


class WxClawAccountInfo(BaseModel):
    account_id: str
    token: str = ""
    base_url: str = "https://ilinkai.weixin.qq.com"
    enabled: bool = True


class Config(BaseModel):
    wxclaw_accounts: list[WxClawAccountInfo] = Field(default_factory=list)
    wxclaw_ilink_app_id: str = "bot"
    wxclaw_channel_version: str = "2.1.1"
    wxclaw_long_poll_timeout: int = 35000
    wxclaw_api_timeout: int = 15000
    wxclaw_cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
