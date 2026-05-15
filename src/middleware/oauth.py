"""
GoogleOAuthMiddleware · valida el id_token de Google directamente
(misma estrategia que login-service en Node con google-auth-library).

Soporta dos modos:
  1. `x-apigateway-api-userinfo` (si en el futuro se mete API Gateway delante)
  2. `Authorization: Bearer <id_token>` validado contra GOOGLE_CLIENT_ID
     vía google.oauth2.id_token (lo que hace falta para el flujo
     service-to-service del frontend → estudios-service → documentos-api)

En modo SKIP_AUTH bypassa con un usuario de prueba.
"""
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
TEST_USER = {
    "email": "test@hipotecai.cl",
    "sub": "test-id",
    "name": "Letrado de prueba",
    "email_verified": True,
}


def _verify_google_id_token(token: str, expected_audience: str) -> dict | None:
    """Verifica un Google id_token usando google-auth. Devuelve el payload o None."""
    try:
        from google.oauth2 import id_token as gid_token  # type: ignore
        from google.auth.transport import requests as g_requests  # type: ignore
    except ImportError:
        logger.error("google-auth no está instalado. Agregar a requirements.txt.")
        return None
    try:
        # Acepta clock skew de 60s por si los relojes del cliente y servidor difieren.
        payload = gid_token.verify_oauth2_token(
            token, g_requests.Request(), expected_audience, clock_skew_in_seconds=60
        )
        # Validación básica del issuer
        if payload.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            logger.warning("id_token con issuer inesperado: %s", payload.get("iss"))
            return None
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_oauth2_token falló: %s", exc)
        return None


class GoogleOAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable]):
        # CORS preflights (OPTIONS) van SIN Authorization header por spec del
        # browser. Que pasen para que CORSMiddleware genere el response con
        # los Access-Control-Allow-* headers. La request real (POST/GET) que
        # viene despues sí trae el bearer y la validamos normal.
        if request.method == "OPTIONS":
            return await call_next(request)

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

        user_info: dict | None = None

        # 1) API Gateway (si lo metiéramos delante)
        if userinfo_header:
            try:
                user_info = json.loads(base64.b64decode(userinfo_header).decode())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not decode userinfo: %s", exc)

        # 2) Bearer token de Google (flujo service-to-service real)
        if not user_info and auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if not settings.GOOGLE_CLIENT_ID:
                logger.error("GOOGLE_CLIENT_ID no configurado; no se puede validar bearer.")
                return JSONResponse(status_code=500, content={"status": "error", "code": "NO_CLIENT_ID", "message": "Servicio mal configurado."})
            user_info = _verify_google_id_token(token, settings.GOOGLE_CLIENT_ID)

        if not user_info:
            return JSONResponse(status_code=401, content={"status": "error", "code": "INVALID_TOKEN", "message": "Token inválido o expirado."})

        if user_info.get("email_verified") is False:
            return JSONResponse(status_code=403, content={"status": "error", "code": "EMAIL_NOT_VERIFIED", "message": "Email no verificado."})

        request.state.user = user_info
        return await call_next(request)
