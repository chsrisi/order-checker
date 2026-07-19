import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from .. import queries
from ...models import WSMessageType, OutboundResponse, StockResponse, PickItemEntryResponse

logger = logging.getLogger("backend.services.managers.connection_manager")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.user_scopes: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, username: str, scope: str):
        await websocket.accept()
        if username not in self.active_connections:
            self.active_connections[username] = []
        self.active_connections[username].append(websocket)
        self.user_scopes[websocket] = scope
        logger.info(f"WebSocket connected: {username} (scope: {scope})")
        logger.debug(
            f"User {username} now has {len(self.active_connections[username])} active sessions"
        )

    def disconnect(self, websocket: WebSocket, username: str):
        if username in self.active_connections:
            self.active_connections[username].remove(websocket)
            if not self.active_connections[username]:
                del self.active_connections[username]
        if websocket in self.user_scopes:
            del self.user_scopes[websocket]
        logger.info(f"WebSocket disconnected: {username}")
        if username in self.active_connections:
            logger.debug(
                f"User {username} has {len(self.active_connections[username])} sessions remaining"
            )
        else:
            logger.debug(f"User {username} has no sessions remaining")

    def _get_data(self, message_type: WSMessageType, username: str):
        is_admin = False
        user = queries.get_user_data(username)
        if user:
            is_admin = user.scope == "admin"
        else:
            raise ValueError(f"User {username} not found")

        data = None

        if message_type == WSMessageType.USERS:
            data = queries.get_all_user_data()
        elif message_type == WSMessageType.OUTBOUNDS:
            outbounds = (
                queries.get_all_outbound_data()
                if is_admin
                else queries.get_outbounds_data(username)
            )
            data = [OutboundResponse.model_validate(o) for o in outbounds]
        elif message_type == WSMessageType.SHOPEE_ORDERS:
            from ..shopee_service import build_shopee_order_response
            orders = (
                queries.get_all_shopee_order_data()
                if is_admin
                else queries.get_shopee_order_data(username)
            )
            data = [build_shopee_order_response(o) for o in orders]
        elif message_type == WSMessageType.PICK_ITEM_ENTRIES:
            entries = queries.get_pie_data(username=None if is_admin else username)
            data = []
            for entry in entries:
                item = queries.resolve_barcode_to_item(entry.sku or "")
                item_name = item.item_name if item else None
                data.append(
                    PickItemEntryResponse(
                        id=entry.id,
                        sku=entry.sku or "",
                        qty=entry.qty or 0,
                        order_sn=entry.order_sn,
                        timestamp=entry.timestamp,
                        owner_user=entry.owner_user,
                        item_name=item_name,
                    )
                )
        elif message_type == WSMessageType.STOCKS:
            stocks = queries.get_all_stocks_data(join_warehouse=True)
            data = [StockResponse.model_validate(dict(s._mapping)) for s in stocks]

        if data is not None:
            data = [jsonable_encoder(item) for item in data]

        return data

    async def _send_raw(
        self,
        message_type: WSMessageType,
        data: Any,
        websocket: WebSocket,
        username: str,
    ):
        try:
            await websocket.send_json({"type": message_type.value, "data": data})
        except Exception as e:
            logger.error(f"Error sending message to {username}: {str(e)}")
            self.disconnect(websocket, username)

    async def send_to_session(
        self,
        message_type: WSMessageType,
        websocket: WebSocket,
        username: str,
        data: Any = None,
    ):
        if data is None:
            data = self._get_data(message_type, username)
        logger.debug(f"Sending {message_type.value} to {username} session")
        await self._send_raw(message_type, data, websocket, username)

    async def send_to_user(self, message_type: WSMessageType, username: str):
        if username in self.active_connections:
            data = self._get_data(message_type, username)
            connections = list(self.active_connections[username])
            logger.debug(
                f"Sending {message_type.value} to {username} ({len(connections)} sessions)"
            )
            tasks = [
                self._send_raw(message_type, data, ws, username) for ws in connections
            ]
            await asyncio.gather(*tasks)

    async def broadcast(self, message_type: WSMessageType, scope: Optional[str] = None):
        admin_data = None
        client_data_cache: dict[str, list[Any] | None] = {}

        tasks: list[Any] = []
        for username, connections in list(self.active_connections.items()):
            for ws in list(connections):
                user_scope = self.user_scopes.get(ws)
                if scope is None or user_scope == scope:
                    if user_scope == "admin":
                        if admin_data is None:
                            admin_data = self._get_data(message_type, username)
                        data = admin_data
                    else:
                        if username not in client_data_cache:
                            client_data_cache[username] = self._get_data(
                                message_type, username
                            )
                        data = client_data_cache[username]

                    tasks.append(self._send_raw(message_type, data, ws, username))

        logger.debug(
            f"Broadcasting {message_type.value} to {len(tasks)} sessions (scope: {scope})"
        )
        if tasks:
            await asyncio.gather(*tasks)
