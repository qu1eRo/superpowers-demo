from datetime import datetime

from pydantic import BaseModel, Field


class SendCodeRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")


class VerifyRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    code: str = Field(pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    phone: str
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VerifyResponse(TokenPair):
    user_id: int
    is_new: bool
