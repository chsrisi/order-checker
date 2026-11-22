package com.bakingholic.orderchecker.updater

import com.bakingholic.orderchecker.api.model.ClientReleaseResponse

/** What the published release means for the installed app (V2_SPEC §4.4). */
sealed interface UpdateDecision {
    data object UpToDate : UpdateDecision

    /** A newer build exists; the operator may postpone it ("Later"). */
    data class Optional(val release: ClientReleaseResponse) : UpdateDecision

    /** The installed build is below `min_supported_version_code`: the app is blocked. */
    data class Required(val release: ClientReleaseResponse) : UpdateDecision
}

object UpdatePolicy {
    fun decide(installedVersionCode: Int, release: ClientReleaseResponse?): UpdateDecision {
        if (release == null || release.versionCode <= installedVersionCode) {
            return UpdateDecision.UpToDate
        }
        val minimum = release.minSupportedVersionCode
        return if (minimum != null && installedVersionCode < minimum) {
            UpdateDecision.Required(release)
        } else {
            UpdateDecision.Optional(release)
        }
    }
}
