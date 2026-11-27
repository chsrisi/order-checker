package com.bakingholic.orderchecker.ops

import com.bakingholic.orderchecker.api.model.OutboundCreate
import com.bakingholic.orderchecker.api.model.OutboundResponse
import com.bakingholic.orderchecker.api.model.OrderPickRequest
import com.bakingholic.orderchecker.api.model.OrderPickResponse
import com.bakingholic.orderchecker.api.model.ShopeeOrderResponse
import com.bakingholic.orderchecker.api.model.StockCreate
import com.bakingholic.orderchecker.api.model.StockUpdateResponse
import com.bakingholic.orderchecker.api.model.WarehouseItemResponse
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.net.ApiRequest
import com.bakingholic.orderchecker.net.ApiResponse
import com.bakingholic.orderchecker.ws.WsClient
import com.bakingholic.orderchecker.ws.WsEventType
import com.bakingholic.orderchecker.ws.WsFrame
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.URLEncoder

/** A row of the `stocks_update` frame (WS payloads are not in the OpenAPI export). */
@Serializable
data class StockRow(
    val id: Int = 0,
    val sku: String,
    val stock: Int,
    val location: String? = null,
    @SerialName("item_name") val itemName: String? = null,
)

/** A row of the `pick_item_entries_update` frame, shared with v1. */
@Serializable
private data class PickRow(
    val sku: String,
    val qty: Int,
    @SerialName("order_sn") val orderSn: String? = null,
    @SerialName("item_name") val itemName: String? = null,
)

/** Outcome of an operator action: the decoded body, or the HTTP status and the API's detail. */
sealed interface ActionResult<out T> {
    data class Ok<T>(val value: T) : ActionResult<T>

    data class Failed(val code: Int, val detail: String) : ActionResult<Nothing>
}

/**
 * Orders, picks, outbound history and stock as the server pushes them over `/v2/ws` (snapshots
 * requested on every connect, like v1), plus the operator actions over `/v2` HTTP. The lists are
 * dropped on logout.
 */
class OpsRepository(
    private val session: SessionManager,
    private val ws: WsClient,
    scope: CoroutineScope,
) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val _orders = MutableStateFlow<List<ShopeeOrderResponse>>(emptyList())
    val orders: StateFlow<List<ShopeeOrderResponse>> = _orders
    private val _picks = MutableStateFlow<List<OrderPick>>(emptyList())
    val picks: StateFlow<List<OrderPick>> = _picks
    private val _outbounds = MutableStateFlow<List<OutboundResponse>>(emptyList())
    val outbounds: StateFlow<List<OutboundResponse>> = _outbounds
    private val _stocks = MutableStateFlow<List<StockRow>>(emptyList())
    val stocks: StateFlow<List<StockRow>> = _stocks

    /** False between logout and the next order snapshot: an empty list then means nothing. */
    private val _ordersLoaded = MutableStateFlow(false)
    val ordersLoaded: StateFlow<Boolean> = _ordersLoaded

    init {
        scope.launch {
            ws.state.collect { if (it == WsClient.State.CONNECTED) requestSnapshots() }
        }
        scope.launch {
            ws.frames.collect { frame -> if (frame is WsFrame.Event) apply(frame.type, frame.data) }
        }
    }

    fun requestSnapshots() {
        ws.send("get_shopee_orders") // orders and pick entries
        ws.send("get_items") // outbound history
        ws.send("get_stocks")
    }

    private fun <T> decode(serializer: KSerializer<T>, data: JsonArray): List<T> =
        runCatching { json.decodeFromJsonElement(ListSerializer(serializer), data) }.getOrDefault(emptyList())

    internal fun apply(type: WsEventType, data: JsonArray) {
        when (type) {
            WsEventType.SHOPEE_ORDERS -> {
                _orders.value = decode(ShopeeOrderResponse.serializer(), data)
                _ordersLoaded.value = true
            }
            WsEventType.PICK_ITEM_ENTRIES -> _picks.value = decode(PickRow.serializer(), data)
                // Rows without an order are v1's pool, which v2 does not have (V2_PICKING_DELTA Q66).
                .mapNotNull { row -> row.orderSn?.let { OrderPick(it, row.sku, row.itemName, row.qty) } }
            WsEventType.OUTBOUNDS -> _outbounds.value = decode(OutboundResponse.serializer(), data)
                .sortedByDescending { it.createdAt }
            WsEventType.STOCKS -> _stocks.value = decode(StockRow.serializer(), data)
            WsEventType.USERS -> Unit
        }
    }

    fun clear() {
        _ordersLoaded.value = false // before the list empties: see OpsController
        _orders.value = emptyList()
        _picks.value = emptyList()
        _outbounds.value = emptyList()
        _stocks.value = emptyList()
    }

    private fun detail(response: ApiResponse): String = runCatching {
        val element = json.parseToJsonElement(response.body).jsonObject["detail"]
        element?.jsonPrimitive?.contentOrNull ?: element.toString()
    }.getOrNull() ?: "Status ${response.code}"

    private suspend fun <T> call(request: ApiRequest, parse: (String) -> T): ActionResult<T> {
        val response = runCatching { session.authorized(request) }.getOrElse {
            return ActionResult.Failed(0, it.message ?: "Cannot reach the server")
        }
        return if (response.isSuccessful) ActionResult.Ok(parse(response.body)) else ActionResult.Failed(response.code, detail(response))
    }

    private inline fun <reified T> body(value: T, serializer: KSerializer<T>) = json.encodeToString(serializer, value)

    suspend fun acquire(orderSn: String) = call(ApiRequest("POST", "/v2/shopee/orders/acquire", query = mapOf("order_sn" to orderSn))) { }

    /** v1's "backend refresh" when an order is not found: a Shopee sync. */
    suspend fun syncOrders() = call(ApiRequest("GET", "/v2/shopee/orders", query = mapOf("refresh" to "true"))) { }

    /** Picks straight into the order (V2_PICKING_SPEC); answers the resolved SKU and its total. */
    suspend fun pick(orderSn: String, sku: String, qty: Int) = orderPicks(orderSn, "", sku, qty)

    /** Takes [qty] off the order and returns it to stock. */
    suspend fun unassign(orderSn: String, sku: String, qty: Int) = orderPicks(orderSn, "/unassign", sku, qty)

    private suspend fun orderPicks(orderSn: String, suffix: String, sku: String, qty: Int) = call(
        ApiRequest(
            "POST",
            // The label is scanned text: escape it as one path segment.
            "/v2/shopee/orders/${URLEncoder.encode(orderSn, "UTF-8").replace("+", "%20")}/picks$suffix",
            jsonBody = body(OrderPickRequest(qty = qty, sku = sku), OrderPickRequest.serializer()),
        ),
    ) { json.decodeFromString(OrderPickResponse.serializer(), it) }

    suspend fun outbound(content: String) = call(
        ApiRequest("POST", "/v2/outbound", jsonBody = body(OutboundCreate(content = content), OutboundCreate.serializer())),
    ) { }

    suspend fun findItems(query: String) = call(ApiRequest("GET", "/v2/items/find", query = mapOf("query" to query))) {
        json.decodeFromString(ListSerializer(WarehouseItemResponse.serializer()), it)
    }

    suspend fun updateStock(sku: String, qty: Int, mode: StockCreate.Mode, location: String?, moveTo: String?) = call(
        ApiRequest(
            "POST",
            "/v2/stocks/update",
            jsonBody = body(StockCreate(sku = sku, stock = qty, location = location, mode = mode, moveTo = moveTo), StockCreate.serializer()),
        ),
    ) { json.decodeFromString(StockUpdateResponse.serializer(), it) }
}
