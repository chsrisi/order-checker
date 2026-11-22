package com.bakingholic.orderchecker.updater

import com.bakingholic.orderchecker.api.model.ClientReleaseResponse
import com.bakingholic.orderchecker.core.AppInfo
import com.bakingholic.orderchecker.net.ServerProfile
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

private fun release(code: Int, min: Int? = null, sha: String = "00", size: Int? = null) =
    ClientReleaseResponse(
        apkUrl = "/v2/client/apk/$code",
        sha256 = sha,
        versionCode = code,
        versionName = "2.0.$code",
        minSupportedVersionCode = min,
        sizeBytes = size,
    )

class UpdatePolicyTest {
    @Test
    fun versionCompare() {
        assertEquals(UpdateDecision.UpToDate, UpdatePolicy.decide(3, null))
        assertEquals(UpdateDecision.UpToDate, UpdatePolicy.decide(3, release(3)))
        assertEquals(UpdateDecision.UpToDate, UpdatePolicy.decide(3, release(2))) // never downgrade
        assertTrue(UpdatePolicy.decide(3, release(4)) is UpdateDecision.Optional)
    }

    @Test
    fun blockingVsOptional() {
        assertTrue(UpdatePolicy.decide(3, release(5, min = 4)) is UpdateDecision.Required)
        assertTrue(UpdatePolicy.decide(4, release(5, min = 4)) is UpdateDecision.Optional)
        assertTrue(UpdatePolicy.decide(3, release(5, min = null)) is UpdateDecision.Optional)
    }
}

class ApkVerifierTest {
    private val installed = PackageIdentity("com.bakingholic.orderchecker", 3, setOf("aa"))

    private fun verifier(archive: PackageIdentity?) = ApkVerifier(
        object : PackageInspector {
            override fun installed() = installed

            override fun archive(apk: File) = archive
        },
    )

    private fun apk(content: String): Pair<File, String> {
        val f = Files.createTempFile("app", ".apk").toFile().apply { writeText(content) }
        return f to ApkVerifier.sha256(f)
    }

    @Test
    fun acceptsSamePackageSameSignerNewerVersion() {
        val (f, sha) = apk("v4")
        assertNull(verifier(installed.copy(versionCode = 4)).verify(f, sha.uppercase()))
    }

    @Test
    fun hashMismatchIsRejectedBeforeAnythingElse() {
        val (f, _) = apk("v4")
        assertEquals(RejectReason.HASH_MISMATCH, verifier(installed.copy(versionCode = 4)).verify(f, "deadbeef"))
    }

    @Test
    fun signerPackageVersionAndJunkAreRejected() {
        val (f, sha) = apk("v4")
        assertEquals(RejectReason.WRONG_SIGNER, verifier(installed.copy(versionCode = 4, signerDigests = setOf("bb"))).verify(f, sha))
        assertEquals(RejectReason.WRONG_SIGNER, verifier(installed.copy(versionCode = 4, signerDigests = emptySet())).verify(f, sha))
        assertEquals(RejectReason.WRONG_PACKAGE, verifier(installed.copy(packageName = "evil.app", versionCode = 4)).verify(f, sha))
        assertEquals(RejectReason.NOT_NEWER, verifier(installed.copy(versionCode = 3)).verify(f, sha))
        assertEquals(RejectReason.UNREADABLE, verifier(null).verify(f, sha))
    }
}

class UpdateCheckerAndManagerTest {
    private lateinit var primary: MockWebServer
    private lateinit var fallback: MockWebServer
    private val app = AppInfo(3, "2.0.3")

    @Before
    fun setUp() {
        primary = MockWebServer().apply { start() }
        fallback = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        primary.shutdown()
        fallback.shutdown()
    }

    private fun base(s: MockWebServer) = s.url("/").toString().trimEnd('/')

    private fun checker(profile: ServerProfile) = UpdateChecker(OkHttpClient(), app, { profile }, Dispatchers.IO)

    private fun releaseJson(code: Int, min: Int?, sha: String, size: Int) =
        """{"version_code":$code,"version_name":"2.0.$code","apk_url":"/v2/client/apk/$code","sha256":"$sha",""" +
            """"size_bytes":$size,"min_supported_version_code":${min ?: "null"},"notes":null,"published_at":null}"""

    @Test
    fun noNetworkIsUnreachableNotACrash() = runBlocking {
        primary.shutdown()
        val result = checker(ServerProfile(base(primary))).latest()
        assertTrue(result is CheckResult.Unreachable)
    }

    @Test
    fun theUpdaterTriesEveryAddress() = runBlocking {
        primary.shutdown() // stage 2 with the tunnel down
        fallback.enqueue(MockResponse().setBody(releaseJson(4, null, "ab", 1)))
        val result = checker(ServerProfile(base(primary), base(fallback))).latest() as CheckResult.Answered
        assertEquals(base(fallback), result.address)
        assertEquals(4, result.release!!.versionCode)
    }

    @Test
    fun nothingPublishedIsAnAnswer() = runBlocking {
        primary.enqueue(MockResponse().setResponseCode(404))
        val result = checker(ServerProfile(base(primary))).latest() as CheckResult.Answered
        assertNull(result.release)
    }

    private class FakeInstaller(var allowed: Boolean = true) : ApkInstaller {
        val installed = mutableListOf<File>()
        var settingsOpened = 0

        override fun canInstall() = allowed

        override fun openInstallPermissionSettings() {
            settingsOpened++
        }

        override fun install(apk: File) {
            installed += apk
        }
    }

    private fun manager(installer: FakeInstaller, archiveVersion: Long = 4): UpdateManager {
        val inspector = object : PackageInspector {
            override fun installed() = PackageIdentity("p", 3, setOf("k"))

            override fun archive(apk: File) = PackageIdentity("p", archiveVersion, setOf("k"))
        }
        return UpdateManager(
            app,
            checker(ServerProfile(base(primary))),
            ApkVerifier(inspector),
            installer,
            Files.createTempDirectory("updates").toFile(),
        )
    }

    private fun publish(code: Int, min: Int?, body: ByteArray, sha: String = ApkVerifier.sha256(body.inputStream())) {
        primary.enqueue(MockResponse().setBody(releaseJson(code, min, sha, body.size)))
        primary.enqueue(MockResponse().setBody(Buffer().write(body)))
    }

    @Test
    fun requiredUpdateDownloadsVerifiesAndInstalls() = runBlocking {
        val installer = FakeInstaller()
        val m = manager(installer)
        publish(4, min = 4, body = "apk-v4".toByteArray())
        assertTrue(m.check() is UpdateDecision.Required)
        assertTrue((m.state.value as UpdateState.Available).required)
        m.update()
        assertEquals(1, installer.installed.size)
        assertEquals("apk-v4", installer.installed.single().readText())
        assertTrue(m.state.value is UpdateState.Installing)
        assertEquals("/v2/client/latest", primary.takeRequest().path)
        assertEquals("/v2/client/apk/4", primary.takeRequest().path)
        m.installFinished(false, "User cancelled")
        assertEquals("User cancelled", (m.state.value as UpdateState.Failed).reason)
    }

    @Test
    fun damagedDownloadIsNotInstalled() = runBlocking {
        val installer = FakeInstaller()
        val m = manager(installer)
        publish(4, min = null, body = "apk-v4".toByteArray(), sha = "00ff")
        m.check()
        m.update()
        assertTrue(installer.installed.isEmpty())
        assertEquals(RejectReason.HASH_MISMATCH.message, (m.state.value as UpdateState.Failed).reason)
    }

    @Test
    fun missingInstallPermissionOpensSettings() = runBlocking {
        val installer = FakeInstaller(allowed = false)
        val m = manager(installer)
        publish(4, min = null, body = "x".toByteArray())
        m.check()
        m.update()
        assertEquals(1, installer.settingsOpened)
        assertEquals(UpdateManager.PERMISSION_MESSAGE, (m.state.value as UpdateState.Failed).reason)
    }

    @Test
    fun laterHidesAnOptionalUpdateUntilANewerOne() = runBlocking {
        val m = manager(FakeInstaller())
        primary.enqueue(MockResponse().setBody(releaseJson(4, null, "ab", 1)))
        m.check()
        m.postpone()
        assertEquals(UpdateState.UpToDate, m.state.value)
        primary.enqueue(MockResponse().setBody(releaseJson(4, null, "ab", 1)))
        m.check()
        assertEquals(UpdateState.UpToDate, m.state.value)
        primary.enqueue(MockResponse().setBody(releaseJson(5, null, "ab", 1)))
        m.check()
        assertTrue(m.state.value is UpdateState.Available)
    }
}
