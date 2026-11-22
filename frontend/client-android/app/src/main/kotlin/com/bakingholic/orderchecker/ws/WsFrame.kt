package com.bakingholic.orderchecker.ws

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Event types of contract v2 (`docs/API.md` "WebSocket protocol"). */
enum class WsEventType(val wire: String) {
    USERS("users_update"),
    OUTBOUNDS("outbound_update"),
    SHOPEE_ORDERS("shopee_orders_update"),
    PICK_ITEM_ENTRIES("pick_item_entries_update"),
    STOCKS("stocks_update"),
    ;

    companion object {
        fun of(wire: String): WsEventType? = entries.firstOrNull { it.wire == wire }
    }
}

/** One `/v2/ws` frame: `{type, data, ts}`. `type` is read first; unknown types are ignored. */
sealed interface WsFrame {
    data class Event(val type: WsEventType, val data: JsonArray, val ts: String?) : WsFrame

    data class Error(val detail: String) : WsFrame

    data class Unknown(val type: String?) : WsFrame

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parse(text: String): WsFrame {
            val obj = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return Unknown(null)
            val type = obj["type"]?.jsonPrimitive?.contentOrNull ?: return Unknown(null)
            val data = runCatching { obj["data"]?.jsonArray }.getOrNull() ?: JsonArray(emptyList())
            if (type == "error") {
                val detail = data.firstOrNull()?.let { runCatching { it.jsonObject["detail"]?.jsonPrimitive?.contentOrNull }.getOrNull() }
                return Error(detail ?: "error")
            }
            val known = WsEventType.of(type) ?: return Unknown(type)
            return Event(known, data, obj["ts"]?.jsonPrimitive?.contentOrNull)
        }
    }
}

/** What to do when the socket closes (T6.11, backend close codes from T6.4). */
enum class CloseAction { RECONNECT, NEW_TICKET_NOW, LOG_OUT, UPDATE_REQUIRED }

object CloseRules {
    const val BAD_REQUEST = 4400
    const val UNAUTHORIZED = 4401
    const val UPGRADE_REQUIRED = 4426
    const val SESSION_REVOKED = 1008

    /** [retriedTicket]: a fresh ticket was already tried after a 4401. */
    fun action(code: Int, retriedTicket: Boolean): CloseAction = when (code) {
        UPGRADE_REQUIRED -> CloseAction.UPDATE_REQUIRED
        UNAUTHORIZED -> if (retriedTicket) CloseAction.LOG_OUT else CloseAction.NEW_TICKET_NOW
        // 1008: the session was revoked; the next authorized call confirms it with a 401.
        SESSION_REVOKED -> if (retriedTicket) CloseAction.LOG_OUT else CloseAction.NEW_TICKET_NOW
        else -> CloseAction.RECONNECT
    }
}
