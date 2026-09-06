from fastapi import APIRouter, Depends

from app.api.deps import get_auth_service, get_current_user
from app.db.models import User
from app.schemas.auth import RefreshRequest, SendCodeRequest, TokenPair, UserOut, VerifyRequest, VerifyResponse
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


@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest,
                  svc: AuthService = Depends(get_auth_service)) -> TokenPair:
    return await svc.refresh(req.refresh_token)


@router.post("/logout", status_code=204)
async def logout(req: RefreshRequest,
                 svc: AuthService = Depends(get_auth_service)) -> None:
    await svc.logout(req.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, phone=user.phone, created_at=user.created_at)
