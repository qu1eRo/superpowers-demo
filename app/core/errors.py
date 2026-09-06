class AppError(Exception):
    status: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "内部错误"


class RateLimitedError(AppError):
    status, code, message = 429, "RATE_LIMITED", "发送过于频繁，请稍后再试"


class TooManyAttemptsError(AppError):
    status, code, message = 429, "TOO_MANY_ATTEMPTS", "尝试次数过多，请稍后再试"


class InvalidCodeError(AppError):
    status, code, message = 400, "INVALID_CODE", "验证码错误或已过期"


class InvalidTokenError(AppError):
    status, code, message = 401, "INVALID_TOKEN", "令牌无效或已过期"


class InternalError(AppError):
    status, code, message = 500, "INTERNAL_ERROR", "内部错误"
