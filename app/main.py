from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError


def create_app() -> FastAPI:
    app = FastAPI(title="Phone Auth API", version="0.1.0")

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "内部错误"})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
