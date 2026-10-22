from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.application.ports import TrackerError
from app.domain.errors import (
    ConflictError,
    DomainError,
    InvalidInputError,
    NotFoundError,
)

_STATUS = {NotFoundError: 404, ConflictError: 409, InvalidInputError: 422}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TrackerError)
    async def tracker_error(_: Request, e: TrackerError):
        return JSONResponse({"detail": f"Keitaro: {e.detail}"}, status_code=502)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, e: DomainError):
        return JSONResponse({"detail": str(e)}, status_code=_STATUS.get(type(e), 400))
