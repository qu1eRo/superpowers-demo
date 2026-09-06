import pytest

from app.providers import AliyunSmsProvider, MockSmsProvider, make_sms_provider
from app.providers.base import SmsProvider


async def test_mock_provider_records_send():
    p = MockSmsProvider()
    await p.send_code("13800000001", "004237")
    assert p.sent == [("13800000001", "004237")]


async def test_mock_provider_is_sms_provider():
    assert isinstance(MockSmsProvider(), SmsProvider)


async def test_aliyun_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await AliyunSmsProvider().send_code("13800000001", "004237")


def test_factory_selects_provider():
    assert isinstance(make_sms_provider("mock"), MockSmsProvider)
    assert isinstance(make_sms_provider("aliyun"), AliyunSmsProvider)


def test_factory_unknown_name_raises():
    with pytest.raises(ValueError):
        make_sms_provider("twilio")
