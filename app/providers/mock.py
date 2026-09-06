from app.providers.base import SmsProvider


class MockSmsProvider(SmsProvider):
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_code(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))
        print(f"[MOCK SMS] {phone} -> {code}")
