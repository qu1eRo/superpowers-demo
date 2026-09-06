from app.providers.aliyun import AliyunSmsProvider
from app.providers.base import SmsProvider
from app.providers.mock import MockSmsProvider


def make_sms_provider(name: str) -> SmsProvider:
    if name == "mock":
        return MockSmsProvider()
    if name == "aliyun":
        return AliyunSmsProvider()
    raise ValueError(f"未知的短信服务商: {name}")
