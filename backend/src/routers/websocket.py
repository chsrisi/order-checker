import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Header, WebSocket, Query, HTTPException, status
from fastapi.websockets import WebSocketDisconnect

from ..exceptions import ClientUpgradeRequired, DomainException
from ..services import client_releases
from ..services.managers import conn_mgr, ticket_mgr
from ..services import queries
from ..models import WSMessageType

logger = logging.getLogger("backend.routers.websocket")

router = APIRouter(prefix="/ws", tags=["websocket"])
# Contract v2 socket (T6.4); mounted by main.py.
v2_router = APIRouter(prefix="/v2/ws", tags=["v2 · websocket"])

# v2 handshake failures: accept, then close with one of these (P-9).
CLOSE_BAD_REQUEST = 4400  # X-Client-Version missing or malformed
CLOSE_UNAUTHORIZED = 4401  # ticket missing, used, expired, or its session revoked
CLOSE_UPGRADE_REQUIRED = 4426  # client below min_supported_version_code


async def _authenticate(token: Optional[str]):
    """The user behind a one-use ticket whose session is still live, else ``None`` (T6.2)."""
    if token is None:
        return None, None
    claims = await ticket_mgr.consume_ticket(token)
    if not claims or not claims.sid:
        return None, None
    user = await asyncio.to_thread(queries.get_user_for_session, claims.username, claims.sid)
    return user, claims.sid


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    # Contract v1: every rejection happens before accept, as HTTP 403 (frozen).
    user, sid = await _authenticate(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )
    await conn_mgr.connect(websocket, user.username or "", user.scope or "", sid=sid)
    await _serve(websocket, user)


@v2_router.websocket("")
async def websocket_v2_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    x_client_version: Optional[str] = Header(None, alias="X-Client-Version"),
):
    """Contract v2: frames are ``{type, data, ts}``; handshake failures are reported with a
    close code after accept (4400, 4401, 4426) so the app can tell them apart."""
    await websocket.accept()
    try:
        client_releases.check_client_version(x_client_version)
    except ClientUpgradeRequired:
        await websocket.close(code=CLOSE_UPGRADE_REQUIRED)
        return
    except DomainException:
        await websocket.close(code=CLOSE_BAD_REQUEST)
        return
    user, sid = await _authenticate(token)
    if not user:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    await conn_mgr.connect(
        websocket, user.username or "", user.scope or "", sid=sid, contract=2, accept=False
    )
    await _serve(websocket, user)


async def _serve(websocket: WebSocket, user) -> None:
    """Command loop shared by both contracts; replies use the socket's own envelope."""
    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command")
            logger.debug(
                "websocket_command_received",
                extra={
                    "event": "websocket.command.received",
                    "username": user.username,
                    "command": command,
                },
            )

            if command == "get_users":
                if user.scope != "admin":
                    await conn_mgr.send_to_session(
                        WSMessageType.ERROR,
                        websocket=websocket,
                        username=user.username,
                        data=conn_mgr.error_payload("Forbidden"),
                    )
                else:
                    await conn_mgr.send_to_session(
                        WSMessageType.USERS,
                        websocket=websocket,
                        username=user.username,
                    )

            elif command == "get_items":
                await conn_mgr.send_to_session(
                    WSMessageType.OUTBOUNDS,
                    websocket=websocket,
                    username=user.username,
                )

            elif command == "get_shopee_orders":
                await conn_mgr.send_to_session(
                    WSMessageType.SHOPEE_ORDERS,
                    websocket=websocket,
                    username=user.username,
                )

                await conn_mgr.send_to_session(
                    WSMessageType.PICK_ITEM_ENTRIES,
                    websocket=websocket,
                    username=user.username,
                )

            elif command == "get_stocks":
                await conn_mgr.send_to_session(
                    WSMessageType.STOCKS,
                    websocket=websocket,
                    username=user.username,
                )

            else:
                await conn_mgr.send_to_session(
                    WSMessageType.ERROR,
                    websocket=websocket,
                    username=user.username,
                    data=conn_mgr.error_payload(f"Unknown command: {str(command)[:64]}"),
                )

    except WebSocketDisconnect:
        conn_mgr.disconnect(websocket, user.username or "")
    except Exception:
        logger.exception(
            "websocket_session_failed",
            extra={"event": "websocket.session.failed", "username": user.username},
        )
        conn_mgr.disconnect(websocket, user.username or "")
