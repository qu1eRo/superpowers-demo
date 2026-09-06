from abc import ABC, abstractmethod


class SmsProvider(ABC):
    @abstractmethod
    async def send_code(self, phone: str, code: str) -> None:
        """发送验证码短信。实现方应自行处理重试与异常上报。"""
