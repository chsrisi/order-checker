package com.bakingholic.orderchecker.updater

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import androidx.core.net.toUri
import android.provider.Settings
import com.bakingholic.orderchecker.OrderCheckerApp
import com.bakingholic.orderchecker.updater.ApkVerifier.Companion.toHex
import java.io.File
import java.security.MessageDigest

/** PackageManager-backed [PackageInspector]. */
class AndroidPackageInspector(private val context: Context) : PackageInspector {
    private val pm: PackageManager get() = context.packageManager

    override fun installed(): PackageIdentity =
        identity(pm.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES))
            ?: error("Installed package has no signing information")

    override fun archive(apk: File): PackageIdentity? {
        val info = pm.getPackageArchiveInfo(apk.path, PackageManager.GET_SIGNING_CERTIFICATES) ?: return null
        return identity(info) ?: legacyIdentity(apk)
    }

    private fun identity(info: PackageInfo): PackageIdentity? {
        val signers = info.signingInfo?.let { si ->
            if (si.hasMultipleSigners()) si.apkContentsSigners else si.signingCertificateHistory
        } ?: return null
        return PackageIdentity(info.packageName, info.longVersionCode, signers.map { digest(it.toByteArray()) }.toSet())
    }

    /** Some Android 11 builds return no signingInfo for archives; GET_SIGNATURES still works. */
    @Suppress("DEPRECATION")
    private fun legacyIdentity(apk: File): PackageIdentity? {
        val info = pm.getPackageArchiveInfo(apk.path, PackageManager.GET_SIGNATURES) ?: return null
        val signatures = info.signatures ?: return null
        return PackageIdentity(info.packageName, info.longVersionCode, signatures.map { digest(it.toByteArray()) }.toSet())
    }

    private fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).toHex()
}

/** [ApkInstaller] through a PackageInstaller session; the result comes to [InstallResultReceiver]. */
class PackageInstallerApkInstaller(private val context: Context) : ApkInstaller {
    override fun canInstall(): Boolean = context.packageManager.canRequestPackageInstalls()

    override fun openInstallPermissionSettings() {
        context.startActivity(
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, "package:${context.packageName}".toUri())
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    override fun install(apk: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            .apply { setAppPackageName(context.packageName); setSize(apk.length()) }
        val sessionId = installer.createSession(params)
        installer.openSession(sessionId).use { session ->
            apk.inputStream().use { input ->
                session.openWrite("base.apk", 0, apk.length()).use { output ->
                    input.copyTo(output)
                    session.fsync(output)
                }
            }
            val intent = Intent(context, InstallResultReceiver::class.java).setPackage(context.packageName)
            val pending = PendingIntent.getBroadcast(
                context,
                sessionId,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
            )
            session.commit(pending.intentSender)
        }
    }
}

/** Receives PackageInstaller status: asks the user to confirm, then reports the outcome. */
class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val updates = (context.applicationContext as OrderCheckerApp).graph.updates
        when (val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)?.let(context::startActivity)
            }
            PackageInstaller.STATUS_SUCCESS -> updates.installFinished(true, null)
            else -> updates.installFinished(
                false,
                intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "Install failed (status $status)",
            )
        }
    }
}
