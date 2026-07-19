from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from starlette.responses import Response

from src.exceptions import DomainException, domain_exception_handler
from src.main import log_requests


def request(path="/test", request_id=None):
    headers = [] if request_id is None else [(b"x-request-id", request_id.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
async def test_request_middleware_preserves_supplied_request_id():
    response = await log_requests(
        request(request_id="caller-id"), AsyncMock(return_value=Response())
    )
    assert response.headers["X-Request-ID"] == "caller-id"


@pytest.mark.asyncio
async def test_request_middleware_generates_request_id():
    response = await log_requests(request(), AsyncMock(return_value=Response(status_code=204)))
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.asyncio
async def test_request_middleware_bounds_untrusted_request_id():
    response = await log_requests(request(request_id="x" * 500), AsyncMock(return_value=Response()))
    assert response.headers["X-Request-ID"] == "x" * 128


@pytest.mark.asyncio
async def test_request_middleware_reraises_application_error():
    with pytest.raises(RuntimeError, match="boom"):
        await log_requests(request(), AsyncMock(side_effect=RuntimeError("boom")))


@pytest.mark.asyncio
async def test_domain_exception_handler_uses_stable_envelope():
    response = await domain_exception_handler(request(), DomainException(409, "conflict"))
    assert response.status_code == 409
    assert response.body == b'{"detail":"conflict"}'
