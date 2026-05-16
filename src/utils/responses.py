"""JSend helpers.

Usamos `jsonable_encoder` para serializar el `content` antes de que
JSONResponse haga su `json.dumps` interno. Sin esto, valores como
Decimal (columnas NUMERIC de Postgres), datetime (created_at del blob de
anchors), UUID y bytes revientan con TypeError. jsonable_encoder de
FastAPI traduce todos esos a tipos json-nativos (float, ISO string, str).
"""
from typing import Any
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(data: Any = None, message: str | None = None, status_code: int = 200):
    body: dict = {"status": "success"}
    if data is not None:
        body["data"] = data
    if message:
        body["message"] = message
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def error_response(message: str, code: str = "INTERNAL_ERROR", data: Any = None, status_code: int = 500):
    body: dict = {"status": "error", "code": code, "message": message}
    if data is not None:
        body["data"] = data
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))
