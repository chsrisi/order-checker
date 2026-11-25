package com.bakingholic.orderchecker.ui.ops

import com.bakingholic.orderchecker.auth.InMemoryTokenStore
import com.bakingholic.orderchecker.auth.SessionManager
import com.bakingholic.orderchecker.auth.Tokens
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.AddressSelector
import com.bakingholic.orderchecker.net.ApiClient
import com.bakingholic.orderchecker.net.ServerProfile
import com.bakingholic.orderchecker.ops.OpsRepository
import com.bakingholic.orderchecker.ops.OrderPick
import com.bakingholic.orderchecker.ws.WsClient
import com.bakingholic.orderchecker.ws.WsEventType
import java.util.Base64
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The picking rules of the client (V2_PICKING_SPEC §5) against a fake server. */
class OpsControllerTest {
    private val server = MockWebServer()
    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val messages = LinkedBlockingQueue<UiMessage>()
    private lateinit var repo: OpsRepository
    private lateinit var ops: OpsController

    @Before
    fun setUp() {
        server.start()
        val profile = ServerProfile(server.url("/").toString().trimEnd('/'))
        val info = AppInfo(1, "2.0.0")
        val http = OkHttpClient()
        val session = SessionManager(ApiClient(http, info, { profile }, AddressSelector()), InMemoryTokenStore(Tokens(jwt(), "r")))
        repo = OpsRepository(session, WsClient(http, session, info, { profile }, { null }, {}, scope), scope)
        ops = OpsController(repo, scope)
        scope.launch { ops.messages.collect { messages += it } }
    }

    @After
    fun tearDown() {
        scope.cancel()
        server.shutdown()
    }

    private fun jwt(): String {
        fun part(s: String) = Base64.getUrlEncoder().withoutPadding().encodeToString(s.toByteArray())
        return part("{}") + "." + part("""{"sub":"op","sid":"s","exp":${System.currentTimeMillis() / 1000 + 3600}}""") + ".x"
    }

    private fun orders(vararg sns: String) = repo.apply(
        WsEventType.SHOPEE_ORDERS,
        Json.parseToJsonElement(
            sns.joinToString(",", "[", "]") {
                """{"order_sn":"$it","ship_by":"2026-11-26T00:00:00Z","status":"READY_TO_SHIP","item_list":[{"component_sku":"A","quantity":2}]}"""
            },
        ).jsonArray,
    )

    private fun message(): UiMessage = messages.poll(5, TimeUnit.SECONDS) ?: error("no message")

    private fun answer(code: Int, body: String) = server.enqueue(MockResponse().setResponseCode(code).setBody(body))

    private fun line(sku: String, qty: Int) = answer(200, """{"order_sn":"261125A","sku":"$sku","qty":$qty,"item_name":null}""")

    @Test
    fun itemModeNeedsAnOrder() {
        ops.setItemMode(true)
        assertFalse(ops.itemMode.value)
        ops.scanSku("A")
        ops.pick(1)
        assertEquals("No order selected.", message().text)
        assertEquals(0, server.requestCount)
        ops.selectOrder("261125A")
        assertTrue(ops.itemMode.value)
    }

    @Test
    fun pickGoesIntoTheSelectedOrderAndWarns() {
        orders("261125A")
        ops.selectOrder("261125A")
        line("A", 2)
        ops.scanSku("BARCODE")
        ops.pick(2)
        assertEquals(UiMessage("Scan entry posted."), message())
        val request = server.takeRequest()
        assertEquals("/v2/shopee/orders/261125A/picks", request.path)
        assertEquals("""{"qty":2,"sku":"BARCODE"}""", request.body.readUtf8())
        assertNull(ops.pendingSku.value)

        line("A", 3)
        ops.scanSku("A")
        ops.pick(1)
        assertTrue(message().let { it.alert && it.text.contains("exceeds requirement (2)") })
        line("OTHER", 1)
        ops.scanSku("OTHER")
        ops.pick(1)
        assertTrue(message().let { it.alert && it.text.contains("not part of this order") })
    }

    @Test
    fun scannedOrderNumbersAreOnePathSegment() {
        ops.selectOrder("261125 A/B?#")
        line("A", 1)
        ops.scanSku("A")
        ops.pick(1)
        assertEquals("/v2/shopee/orders/261125%20A%2FB%3F%23/picks", server.takeRequest(5, TimeUnit.SECONDS)!!.path)
    }

    @Test
    fun unassignReturnsToStockAndShowsConflicts() {
        line("A", 0)
        ops.unassign("261125A", "A", 2)
        assertEquals("Returned 2 × A to stock.", message().text)
        assertEquals("/v2/shopee/orders/261125A/picks/unassign", server.takeRequest().path)
        answer(409, """{"detail":"Order already completed"}""")
        ops.unassign("261125A", "A", 1)
        assertEquals(UiMessage("Order already completed", isError = true, alert = true), message())
    }

    @Test
    fun selectionClearsWhenTheOrderLeavesTheList() {
        orders("261125A", "261125B")
        ops.selectOrder("261125A")
        ops.scanSku("A")
        orders("261125A", "261125B")
        assertNotNull(ops.selectedOrder.value)
        // Tapped between two snapshots: still noticed.
        ops.selectOrder("261125B")
        orders("261125A")
        assertNull(ops.selectedOrder.value)
        assertFalse(ops.itemMode.value)
        assertNull(ops.pendingSku.value)
        assertTrue(message().let { it.alert && it.text.contains("261125B") })
    }

    @Test
    fun aFreshClaimKeepsItsSelectionUntilItsFrameArrives() {
        orders("261125B")
        ops.selectOrder("261125A")
        orders("261125B")
        assertEquals("261125A", ops.selectedOrder.value)
        orders("261125A", "261125B")
        assertEquals("261125A", ops.selectedOrder.value)
    }

    @Test
    fun logoutClearsTheSelectionSilently() {
        orders("261125A")
        ops.selectOrder("261125A")
        repo.clear()
        assertNull(ops.selectedOrder.value)
        assertTrue(messages.isEmpty())
    }

    @Test
    fun anotherOrderDropsTheWaitingSku() {
        ops.selectOrder("261125A")
        ops.scanSku("A")
        ops.selectOrder("261125A") // a tap on the same order keeps it
        assertEquals("A", ops.pendingSku.value)
        ops.selectOrder("261125B")
        assertNull(ops.pendingSku.value)
    }

    @Test
    fun poolRowsOfV1AreIgnored() {
        repo.apply(
            WsEventType.PICK_ITEM_ENTRIES,
            Json.parseToJsonElement(
                """[{"id":1,"sku":"A","qty":2,"order_sn":null,"timestamp":"t","owner_user":"op","item_name":null},
                    {"id":2,"sku":"A","qty":3,"order_sn":"261125A","timestamp":"t","owner_user":"op","item_name":"Flour"}]""",
            ).jsonArray,
        )
        assertEquals(listOf(OrderPick("261125A", "A", "Flour", 3)), repo.picks.value)
    }
}
