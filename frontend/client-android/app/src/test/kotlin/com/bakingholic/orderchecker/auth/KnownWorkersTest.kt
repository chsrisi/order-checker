package com.bakingholic.orderchecker.auth

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class KnownWorkersTest {
    private fun withWorkers(block: suspend (KnownWorkers) -> Unit) = runBlocking {
        val dir = Files.createTempDirectory("workers").toFile()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        block(KnownWorkers(PreferenceDataStoreFactory.create(scope = scope) { File(dir, "settings.preferences_pb") }))
        scope.cancel()
    }

    @Test
    fun mostRecentFirstWithoutDuplicates() = withWorkers { workers ->
        assertEquals(emptyList<String>(), workers.names.first())
        listOf("alice", "bob", "alice").forEach { workers.remember(it) }
        assertEquals(listOf("alice", "bob"), workers.names.first())
    }

    @Test
    fun theOldestNameDropsOutAtTheCap() = withWorkers { workers ->
        (0..KnownWorkers.MAX).forEach { workers.remember("w$it") }
        val names = workers.names.first()
        assertEquals(KnownWorkers.MAX, names.size)
        assertEquals("w${KnownWorkers.MAX}", names.first())
        assertEquals("w1", names.last())
    }
}
