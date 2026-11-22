package com.bakingholic.orderchecker.core

/** What the app reports about itself: `X-Client-Version`, the version label, the updater. */
data class AppInfo(val versionCode: Int, val versionName: String) {
    /** Value of the `X-Client-Version` header (backend T6.3): the integer versionCode. */
    val clientVersionHeader: String get() = versionCode.toString()

    val label: String get() = "v$versionName ($versionCode)"

    companion object {
        /** Contract the app speaks; `/v2/meta` must report `client_contract.max >= CONTRACT`. */
        const val CONTRACT = 2

        fun supportsServer(contractMin: Int, contractMax: Int): Boolean = CONTRACT in contractMin..contractMax
    }
}
