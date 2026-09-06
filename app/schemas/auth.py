from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VerifyResponse(TokenPair):
    user_id: int
    is_new: bool
