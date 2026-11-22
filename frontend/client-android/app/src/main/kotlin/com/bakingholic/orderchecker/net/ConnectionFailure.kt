package com.bakingholic.orderchecker.net

import java.io.IOException
import okhttp3.Response

/**
 * What counts as "unreachable" for the switch rule (V2_SERVER_ADDRESS §4.2, flows F4/F5):
 * transport errors (DNS, TCP, TLS, timeouts), Cloudflare 52x/530 origin errors, and Cloudflare
 * Access block pages (an expired or missing service token). Every other HTTP status is a real
 * answer from the backend and never switches addresses.
 */
object ConnectionFailure {
    fun isFailure(error: Throwable): Boolean = error is IOException

    fun isFailure(response: Response): Boolean {
        val code = response.code
        if (code in 520..527 || code == 530) return true
        if (response.header("cf-mitigated") != null) return true
        val location = response.header("Location").orEmpty()
        if (response.isRedirect && location.contains(".cloudflareaccess.com")) return true
        return false
    }
}
