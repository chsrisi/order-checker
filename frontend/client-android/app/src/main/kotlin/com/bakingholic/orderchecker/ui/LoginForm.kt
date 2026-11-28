package com.bakingholic.orderchecker.ui

/** What the login screen shows. */
enum class LoginStep { PICK, PASSWORD, MANUAL }

/** The login screen's input and its transitions, without any UI. */
data class LoginForm(
    val step: LoginStep = LoginStep.PICK,
    /** Picked by hand; until then the last worker of this device is preselected. */
    val picked: String? = null,
    val username: String = "",
    val password: String = "",
) {
    /** [known] is most recent first. */
    fun worker(known: List<String>): String? = picked ?: known.firstOrNull()

    /** A password typed for one worker is never sent for another. */
    fun pick(name: String) = copy(picked = name, password = "")

    /** Login on the first step. Fixes the worker, so a later change of the list cannot swap it. */
    fun askPassword(known: List<String>): LoginForm =
        worker(known)?.let { copy(step = LoginStep.PASSWORD, picked = it, password = "") } ?: this

    /** The admin chose [name] (T8.7): their password step, as if picked by hand. */
    fun preselect(name: String) = copy(step = LoginStep.PASSWORD, picked = name, password = "")

    fun manual() = copy(step = LoginStep.MANUAL, password = "")

    fun back() = copy(step = LoginStep.PICK, password = "")

    /** Username and password to send, or null while something is missing. */
    fun credentials(known: List<String>): Pair<String, String>? {
        val name = when (step) {
            LoginStep.PICK -> null
            LoginStep.PASSWORD -> worker(known)
            LoginStep.MANUAL -> username.trim()
        }
        return if (name.isNullOrBlank() || password.isEmpty()) null else name to password
    }
}
