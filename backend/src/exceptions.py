from fastapi import Request
from fastapi.responses import JSONResponse

class DomainException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail

async def domain_exception_handler(request: Request, exc: Exception):
    status_code = exc.status_code if isinstance(exc, DomainException) else 500
    detail = exc.detail if isinstance(exc, DomainException) else "Internal server error"
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )
