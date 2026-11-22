package com.bakingholic.orderchecker.updater

import java.io.File
import java.io.InputStream
import java.security.MessageDigest

/** What Android reports about a downloaded APK (or about the installed app). */
data class PackageIdentity(
    val packageName: String,
    val versionCode: Long,
    /** SHA-256 hex digests of the signing certificates. */
    val signerDigests: Set<String>,
)

/** Reads package identities; the Android implementation uses PackageManager. */
interface PackageInspector {
    fun installed(): PackageIdentity

    fun archive(apk: File): PackageIdentity?
}

/** Why a download must not be installed. */
enum class RejectReason(val message: String) {
    HASH_MISMATCH("The download is damaged (SHA-256 mismatch)."),
    UNREADABLE("The download is not a valid app package."),
    WRONG_PACKAGE("The download is a different app."),
    WRONG_SIGNER("The download is not signed with this app's key."),
    NOT_NEWER("The download is not newer than the installed app."),
}

/**
 * The checks before handing a file to PackageInstaller (V2_SPEC §12.5). Android enforces the
 * signer and version rules itself; checking first gives the operator a clear message instead
 * of "App not installed".
 */
class ApkVerifier(private val inspector: PackageInspector) {
    fun verify(apk: File, expectedSha256: String): RejectReason? {
        if (!sha256(apk).equals(expectedSha256, ignoreCase = true)) return RejectReason.HASH_MISMATCH
        val candidate = inspector.archive(apk) ?: return RejectReason.UNREADABLE
        val installed = inspector.installed()
        if (candidate.packageName != installed.packageName) return RejectReason.WRONG_PACKAGE
        if (candidate.signerDigests.isEmpty() || candidate.signerDigests != installed.signerDigests) {
            return RejectReason.WRONG_SIGNER
        }
        if (candidate.versionCode <= installed.versionCode) return RejectReason.NOT_NEWER
        return null
    }

    companion object {
        fun sha256(file: File): String = file.inputStream().use { sha256(it) }

        fun sha256(input: InputStream): String {
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
            return digest.digest().toHex()
        }

        fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
    }
}
