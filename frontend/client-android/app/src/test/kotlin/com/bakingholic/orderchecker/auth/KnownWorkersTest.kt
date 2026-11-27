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

    @Test
    fun forgettingANameKeepsTheOthersInOrder() = withWorkers { workers ->
        listOf("carol", "bob", "alice").forEach { workers.remember(it) }
        workers.forget("bob")
        assertEquals(listOf("alice", "carol"), workers.names.first())
        workers.forget("nobody")
        assertEquals(listOf("alice", "carol"), workers.names.first())
    }

    @Test
    fun aForgottenNameComesBackOnTheNextLogin() = withWorkers { workers ->
        listOf("bob", "alice").forEach { workers.remember(it) }
        workers.forget("bob")
        workers.remember("bob")
        assertEquals(listOf("bob", "alice"), workers.names.first())
    }

    @Test
    fun forgetAllEmptiesTheList() = withWorkers { workers ->
        listOf("bob", "alice").forEach { workers.remember(it) }
        workers.forgetAll()
        assertEquals(emptyList<String>(), workers.names.first())
        workers.remember("carol")
        assertEquals(listOf("carol"), workers.names.first())
    }
}
