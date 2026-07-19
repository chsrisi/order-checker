import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, Query, HTTPException, status
from fastapi.websockets import WebSocketDisconnect

from ..services.managers import conn_mgr, ticket_mgr
from ..services import queries
from ..models import WSMessageType

logger = logging.getLogger("backend.routers.websocket")

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    username = await ticket_mgr.consume_ticket(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    user = queries.get_user_data(username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    await conn_mgr.connect(websocket, user.username or "", user.scope or "")
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
                        data="Forbidden",
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
                    data=f"Unknown command: {command}",
                )

    except WebSocketDisconnect:
        conn_mgr.disconnect(websocket, user.username or "")
    except Exception:
        logger.exception(
            "websocket_session_failed",
            extra={"event": "websocket.session.failed", "username": user.username},
        )
        conn_mgr.disconnect(websocket, user.username or "")
