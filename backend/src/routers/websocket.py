import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, Query, HTTPException, status
from fastapi.websockets import WebSocketDisconnect

from ..services.manager import conn_mgr, ticket_mgr
from ..dependencies import ctx_get_db
from ..services import queries
from ..models import WSMessageType

logger = logging.getLogger("backend.routers.websocket")

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
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

    with ctx_get_db() as db:
        user = queries.get_user_data(db, username)
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
                logger.debug(f"WS Command received from {user.username}: {command}")

                if command == "get_users":
                    if user.scope != "admin":
                        await conn_mgr.send_to_session(
                            WSMessageType.ERROR,
                            db,
                            websocket=websocket,
                            username=user.username,
                            data="Forbidden",
                        )
                    else:
                        await conn_mgr.send_to_session(
                            WSMessageType.USERS,
                            db,
                            websocket=websocket,
                            username=user.username,
                        )

                elif command == "get_items":
                    await conn_mgr.send_to_session(
                        WSMessageType.OUTBOUNDS,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                elif command == "get_shopee_orders":
                    await conn_mgr.send_to_session(
                        WSMessageType.SHOPEE_ORDERS,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                    await conn_mgr.send_to_session(
                        WSMessageType.PICK_ITEM_ENTRIES,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                elif command == "get_stocks":
                    await conn_mgr.send_to_session(
                        WSMessageType.STOCKS,
                        db,
                        websocket=websocket,
                        username=user.username,
                    )

                else:
                    await conn_mgr.send_to_session(
                        WSMessageType.ERROR,
                        db,
                        websocket=websocket,
                        username=user.username,
                        data=f"Unknown command: {command}",
                    )

        except WebSocketDisconnect:
            conn_mgr.disconnect(websocket, user.username or "")
        except Exception as e:
            logger.error(f"WebSocket error for {user.username}: {str(e)}")
            conn_mgr.disconnect(websocket, user.username or "")
