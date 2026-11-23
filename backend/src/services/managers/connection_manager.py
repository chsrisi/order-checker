import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from .. import queries
from ...models import (
    OutboundResponse,
    PickItemEntryResponse,
    StockResponse,
    UserResponse,
    WSMessageType,
)

logger = logging.getLogger("backend.services.managers.connection_manager")


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.user_scopes: Dict[WebSocket, str] = {}
        # Session (``sid``) each socket was opened with, so one session can be closed (T6.2).
        self.socket_sessions: Dict[WebSocket, str] = {}
        # Client contract per socket: 1 = root /ws (frozen frames), 2 = /v2/ws (T6.4).
        self.socket_contracts: Dict[WebSocket, int] = {}

    async def connect(
        self,
        websocket: WebSocket,
        username: str,
        scope: str,
        sid: Optional[str] = None,
        contract: int = 1,
        accept: bool = True,
    ):
        if accept:
            await websocket.accept()
        if sid is not None:
            self.socket_sessions[websocket] = sid
        if contract != 1:
            self.socket_contracts[websocket] = contract
        if username not in self.active_connections:
            self.active_connections[username] = []
        self.active_connections[username].append(websocket)
        self.user_scopes[websocket] = scope
        logger.info(f"WebSocket connected: {username} (scope: {scope})")
        logger.debug(
            f"User {username} now has {len(self.active_connections[username])} active sessions"
        )

    def disconnect(self, websocket: WebSocket, username: str):
        # Idempotent: a failed send may already have removed this socket before the
        # router's WebSocketDisconnect handler calls disconnect() again (F-M10).
        sessions = self.active_connections.get(username)
        if sessions is not None:
            if websocket in sessions:
                sessions.remove(websocket)
            if not sessions:
                del self.active_connections[username]
        self.user_scopes.pop(websocket, None)
        self.socket_sessions.pop(websocket, None)
        self.socket_contracts.pop(websocket, None)
        logger.info(f"WebSocket disconnected: {username}")
        if username in self.active_connections:
            logger.debug(
                f"User {username} has {len(self.active_connections[username])} sessions remaining"
            )
        else:
            logger.debug(f"User {username} has no sessions remaining")

    async def disconnect_user(self, username: str, code: int = 1008) -> int:
        """Close and forget every socket of ``username`` (deleted user, reset password).

        A v1 client sees the socket end, asks for a new ticket, fails to refresh (its tokens
        were revoked) and returns to the login screen (F-M9).
        """
        sockets = self.active_connections.pop(username, [])
        for ws in sockets:
            self.user_scopes.pop(ws, None)
            self.socket_sessions.pop(ws, None)
            self.socket_contracts.pop(ws, None)
            try:
                await ws.close(code=code)
            except Exception as e:  # already gone
                logger.debug(f"Closing socket for {username} failed: {e}")
        if sockets:
            logger.info(f"Closed {len(sockets)} WebSocket session(s) for {username}")
        return len(sockets)

    async def disconnect_session(self, sid: str, code: int = 1008) -> int:
        """Close every socket opened with session ``sid`` (logout, revoked session); the
        user's other sessions stay connected."""
        targets = [ws for ws, s in self.socket_sessions.items() if s == sid]
        for ws in targets:
            for username, sockets in list(self.active_connections.items()):
                if ws in sockets:
                    self.disconnect(ws, username)
                    break
            else:
                self.user_scopes.pop(ws, None)
                self.socket_sessions.pop(ws, None)
                self.socket_contracts.pop(ws, None)
            try:
                await ws.close(code=code)
            except Exception as e:  # already gone
                logger.debug(f"Closing socket of session {sid} failed: {e}")
        if targets:
            logger.info(f"Closed {len(targets)} WebSocket session(s) of a revoked session")
        return len(targets)

    def live_session_ids(self) -> set[str]:
        """Sessions with at least one open socket (admin device listing, V2_DELTA Q35)."""
        return set(list(self.socket_sessions.values()))

    # Payloads identical for every recipient: built once per broadcast (T4.5).
    SCOPE_INDEPENDENT = frozenset({WSMessageType.USERS, WSMessageType.STOCKS})

    def _get_data(self, message_type: WSMessageType, username: str, scope: Optional[str] = None):
        """Build a payload for ``username``. Pass ``scope`` when the caller knows it (the
        socket's authenticated scope) to skip the per-recipient user lookup."""
        if scope is None:
            user = queries.get_user_data(username)
            if not user:
                raise ValueError(f"User {username} not found")
            scope = user.scope
        is_admin = scope == "admin"

        data = None

        if message_type == WSMessageType.USERS:
            # Explicit response model: the ORM row also carries password_hash.
            data = [UserResponse.model_validate(u) for u in queries.get_all_user_data()]
        elif message_type == WSMessageType.OUTBOUNDS:
            outbounds = (
                queries.get_all_outbound_data()
                if is_admin
                else queries.get_outbounds_data(username)
            )
            data = [OutboundResponse.model_validate(o) for o in outbounds]
        elif message_type == WSMessageType.SHOPEE_ORDERS:
            from ..shopee_service import build_shopee_order_responses

            orders = (
                queries.get_all_shopee_order_data()
                if is_admin
                else queries.get_shopee_order_data(username)
            )
            data = build_shopee_order_responses(orders)
        elif message_type == WSMessageType.PICK_ITEM_ENTRIES:
            entries = queries.get_pie_data(username=None if is_admin else username)
            names = queries.item_names_for(e.sku for e in entries)
            data = []
            for entry in entries:
                item_name = names.get(entry.sku or "")
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
            stocks = queries.get_stocks_data(join_warehouse=True)
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
            await websocket.send_json(self.frame(message_type, data, websocket))
        except Exception as e:
            logger.error(f"Error sending message to {username}: {str(e)}")
            self.disconnect(websocket, username)

    def frame(self, message_type: WSMessageType, data: Any, websocket: WebSocket) -> dict:
        """The envelope for this socket's contract. The payload (``data``, always a list of
        objects) is shared; only the envelope differs: v1 ``{type, data}`` (frozen), v2
        ``{type, data, ts}`` with ``ts`` the UTC send time (P-9)."""
        frame = {"type": message_type.value, "data": data}
        if self.socket_contracts.get(websocket, 1) >= 2:
            frame["ts"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return frame

    @staticmethod
    def error_payload(detail: str) -> list[dict[str, str]]:
        """Error frames follow the frame rule too: ``data`` is a list of objects."""
        return [{"detail": detail}]

    async def send_to_session(
        self,
        message_type: WSMessageType,
        websocket: WebSocket,
        username: str,
        data: Any = None,
    ):
        if data is None:
            data = await asyncio.to_thread(
                self._get_data, message_type, username, self.user_scopes.get(websocket)
            )
        logger.debug(f"Sending {message_type.value} to {username} session")
        await self._send_raw(message_type, data, websocket, username)

    async def send_to_user(self, message_type: WSMessageType, username: str):
        if username in self.active_connections:
            connections = list(self.active_connections.get(username, []))
            scope = self.user_scopes.get(connections[0]) if connections else None
            data = await asyncio.to_thread(self._get_data, message_type, username, scope)
            logger.debug(
                f"Sending {message_type.value} to {username} ({len(connections)} sessions)"
            )
            tasks = [self._send_raw(message_type, data, ws, username) for ws in connections]
            await asyncio.gather(*tasks)

    async def broadcast(self, message_type: WSMessageType, scope: Optional[str] = None):
        # One payload per audience: every admin shares one, each operator gets their own, and
        # scope-independent types share one for everybody (T4.5).
        payloads: dict[str, Any] = {}

        tasks: list[Any] = []
        for username, connections in list(self.active_connections.items()):
            for ws in list(connections):
                user_scope = self.user_scopes.get(ws)
                if scope is not None and user_scope != scope:
                    continue
                if message_type in self.SCOPE_INDEPENDENT:
                    audience = "*"
                elif user_scope == "admin":
                    audience = "admin"
                else:
                    audience = f"user:{username}"
                if audience not in payloads:
                    payloads[audience] = await asyncio.to_thread(
                        self._get_data, message_type, username, user_scope
                    )
                tasks.append(self._send_raw(message_type, payloads[audience], ws, username))

        logger.debug(f"Broadcasting {message_type.value} to {len(tasks)} sessions (scope: {scope})")
        if tasks:
            await asyncio.gather(*tasks)
