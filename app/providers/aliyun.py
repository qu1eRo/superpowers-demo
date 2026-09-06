from app.providers.base import SmsProvider


class AliyunSmsProvider(SmsProvider):
    async def send_code(self, phone: str, code: str) -> None:
        raise NotImplementedError("阿里云短信尚未接入")
