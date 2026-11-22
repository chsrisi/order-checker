package com.bakingholic.orderchecker.net

/**
 * The address-switch rule (V2_SERVER_ADDRESS §4.2): the active address is the last one that
 * answered; a *connection* failure moves to the other one; an HTTP answer (even 4xx) never
 * switches. While on the fallback, the primary is probed every [probeIntervalMillis].
 * Thread-safe; time is injected for tests.
 */
class AddressSelector(
    private val probeIntervalMillis: Long = 3 * 60_000L,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private var addresses: List<String> = emptyList()
    private var active: String? = null
    private var lastProbe = 0L

    @Synchronized
    fun update(profile: ServerProfile) {
        addresses = profile.addresses
        if (active !in addresses) active = addresses.firstOrNull()
    }

    /** Addresses in the order to try: the active one first, then the others. */
    @Synchronized
    fun order(): List<String> {
        val current = active ?: return addresses
        return listOf(current) + addresses.filter { it != current }
    }

    @Synchronized
    fun answered(address: String) {
        if (address in addresses) active = address
    }

    @Synchronized
    fun connectionFailed(address: String) {
        if (active == address) {
            active = addresses.firstOrNull { it != address } ?: address
        }
    }

    @Synchronized
    fun onFallback(): Boolean = addresses.size > 1 && active != addresses.first()

    /** True when the primary should be probed now (and records the probe time). */
    @Synchronized
    fun primaryProbeDue(): Boolean {
        if (!onFallback()) return false
        val now = clock()
        if (now - lastProbe < probeIntervalMillis) return false
        lastProbe = now
        return true
    }

    @Synchronized
    fun primary(): String? = addresses.firstOrNull()
}
