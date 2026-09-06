from fastapi import APIRouter, Depends

from app.api.deps import get_auth_service
from app.schemas.auth import SendCodeRequest, VerifyRequest, VerifyResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/send-code", status_code=202)
async def send_code(req: SendCodeRequest,
                    svc: AuthService = Depends(get_auth_service)) -> dict:
    expires_in = await svc.send_code(req.phone)
    return {"expires_in": expires_in}


@router.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest,
                 svc: AuthService = Depends(get_auth_service)) -> VerifyResponse:
    return await svc.verify(req.phone, req.code)
