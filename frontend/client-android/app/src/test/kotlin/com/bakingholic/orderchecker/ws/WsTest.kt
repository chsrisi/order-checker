package com.bakingholic.orderchecker.ws

import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WsTest {
    @Test
    fun backoffDoublesToTheCapWithJitterAndNeverGivesUp() {
        val b = Backoff(random = Random(1))
        val delays = (1..12).map { b.next() }
        val nominal = listOf(1_000L, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000, 30_000, 30_000, 30_000, 30_000, 30_000)
        delays.zip(nominal).forEach { (d, n) -> assertTrue("$d vs $n", d in (n * 0.8).toLong()..(n * 1.2).toLong()) }
        b.reset()
        assertTrue(b.next() <= 1_200)
    }

    @Test
    fun framesAreParsedTypeFirst() {
        val frame = WsFrame.parse("""{"type":"stocks_update","data":[{"sku":"A01_001"}],"ts":"2026-11-22T10:00:00Z"}""")
        frame as WsFrame.Event
        assertEquals(WsEventType.STOCKS, frame.type)
        assertEquals(1, frame.data.size)
        assertEquals("2026-11-22T10:00:00Z", frame.ts)
    }

    @Test
    fun errorsUnknownTypesAndJunkAreHandled() {
        assertEquals(WsFrame.Error("Unknown command: x"), WsFrame.parse("""{"type":"error","data":[{"detail":"Unknown command: x"}]}"""))
        assertEquals(WsFrame.Unknown("future_update"), WsFrame.parse("""{"type":"future_update","data":[]}"""))
        assertEquals(WsFrame.Unknown(null), WsFrame.parse("not json"))
        val noData = WsFrame.parse("""{"type":"users_update"}""") as WsFrame.Event
        assertTrue(noData.data.isEmpty())
    }

    @Test
    fun closeCodesMapToActions() {
        assertEquals(CloseAction.UPDATE_REQUIRED, CloseRules.action(4426, false))
        assertEquals(CloseAction.NEW_TICKET_NOW, CloseRules.action(4401, false))
        assertEquals(CloseAction.LOG_OUT, CloseRules.action(4401, true))
        assertEquals(CloseAction.NEW_TICKET_NOW, CloseRules.action(1008, false))
        assertEquals(CloseAction.RECONNECT, CloseRules.action(1001, false))
        assertEquals(CloseAction.RECONNECT, CloseRules.action(-1, true))
    }
}
