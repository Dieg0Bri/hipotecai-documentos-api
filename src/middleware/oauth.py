"""GoogleOAuthMiddleware idéntico al de clasificador-api."""
import base64
import json
import logging
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.config import settings

logger = logging.getLogger(__name__)
PUBLIC_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")
TEST_USER = {"email": "test@hipotecai.cl", "sub": "test-id", "name": "Letrado de prueba", "email_verified": True}


class GoogleOAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        path = request.url.path
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        if settings.SKIP_AUTH or settings.ENVIRONMENT == "test":
            request.state.user = TEST_USER
            return await call_next(request)

        userinfo_header = request.headers.get("x-apigateway-api-userinfo")
        auth_header = request.headers.get("x-forwarded-authorization") or request.headers.get("authorization")
        if not userinfo_header and not auth_header:
            return JSONResponse(status_code=401, content={"status": "error", "code": "NO_AUTH", "message": "Auth requerida."})

        user_info = None
        if userinfo_header:
            try:
                user_info = json.loads(base64.b64decode(userinfo_header).decode())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not decode userinfo: %s", exc)

        if not user_info:
            return JSONResponse(status_code=401, content={"status": "error", "code": "NO_USER_INFO", "message": "Sin info."})

        if user_info.get("email_verified") is False:
            return JSONResponse(status_code=403, content={"status": "error", "code": "EMAIL_NOT_VERIFIED", "message": "Email no verificado."})

        request.state.user = user_info
        return await call_next(request)
