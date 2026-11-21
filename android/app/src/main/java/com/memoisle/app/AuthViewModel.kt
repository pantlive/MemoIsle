package com.memoisle.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.AuthTokenStore
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.network.AuthProvidersResponse
import com.memoisle.app.network.AuthSession
import com.memoisle.app.network.AuthUser
import com.memoisle.app.network.EmailRegisterResponse
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.ui.UiText
import com.memoisle.app.ui.toUiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class AuthStatus {
    LOADING,
    ANONYMOUS,
    AUTHENTICATED,
}

enum class AuthMessageTone {
    ERROR,
    NOTICE,
}

data class AuthUiState(
    val status: AuthStatus = AuthStatus.LOADING,
    val user: AuthUser? = null,
    val providers: AuthProvidersResponse? = null,
    val message: UiText? = null,
    val messageTone: AuthMessageTone = AuthMessageTone.ERROR,
    val isBusy: Boolean = false,
    val isSendingVerificationCode: Boolean = false,
    val verificationCodeCooldownSeconds: Int = 0,
)

class AuthViewModel(
    private val api: MemoApiClient,
    private val tokenStore: AuthTokenStore,
    private val repository: MemoRepository,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = mutableUiState.asStateFlow()
    private var verificationCodeCooldownJob: Job? = null

    init {
        restoreSession()
    }

    fun authorizationUrl(provider: String): String {
        return api.authorizationUrl(provider, MOBILE_REDIRECT_URI)
    }

    fun completeLogin(token: String): Unit {
        if (mutableUiState.value.isBusy) {
            return
        }
        mutableUiState.value = mutableUiState.value.copy(
            isBusy = true,
            message = null,
            status = AuthStatus.LOADING,
        )
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    api.accessToken = token
                    val currentUser = api.getCurrentUser()
                    tokenStore.save(token, currentUser.id)
                    repository.activateUser(currentUser.id)
                    currentUser
                }
            }.fold(
                onSuccess = { user ->
                    mutableUiState.value = AuthUiState(
                        status = AuthStatus.AUTHENTICATED,
                        user = user,
                    )
                },
                onFailure = { error ->
                    tokenStore.clear()
                    api.clearSession()
                    loadAnonymousState(error.toUiText(R.string.auth_error_login_retry))
                },
            )
        }
    }

    fun devLogin(): Unit {
        if (mutableUiState.value.isBusy) {
            return
        }
        mutableUiState.value = mutableUiState.value.copy(isBusy = true, message = null)
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val session = api.devLogin()
                    tokenStore.save(session.accessToken, session.user.id)
                    repository.activateUser(session.user.id)
                    session.user
                }
            }.fold(
                onSuccess = { user ->
                    mutableUiState.value = AuthUiState(
                        status = AuthStatus.AUTHENTICATED,
                        user = user,
                    )
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        status = AuthStatus.ANONYMOUS,
                        isBusy = false,
                        message = error.toUiText(R.string.auth_error_login_later),
                        messageTone = AuthMessageTone.ERROR,
                    )
                },
            )
        }
    }

    fun loginWithEmail(email: String, password: String): Unit {
        submitEmailCredentials(
            email,
            password,
            password,
            verificationCode = "",
            isRegistration = false,
            displayName = null,
        )
    }

    fun requestVerificationCode(email: String, inviteCode: String): Unit {
        val state = mutableUiState.value
        if (state.providers?.inviteRequired == true && inviteCode.isBlank()) {
            mutableUiState.value = state.copy(
                message = UiText.res(R.string.auth_error_invite_required),
                messageTone = AuthMessageTone.ERROR,
            )
            return
        }
        if (
            state.isBusy ||
            state.isSendingVerificationCode ||
            state.verificationCodeCooldownSeconds > 0 ||
            email.isBlank()
        ) {
            return
        }
        mutableUiState.value = state.copy(
            isSendingVerificationCode = true,
            message = null,
            messageTone = AuthMessageTone.ERROR,
        )
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    api.requestVerificationCode(email, inviteCode)
                }
            }.fold(
                onSuccess = {
                    mutableUiState.value = mutableUiState.value.copy(
                        isSendingVerificationCode = false,
                        verificationCodeCooldownSeconds = 60,
                        message = UiText.res(R.string.auth_msg_code_sent),
                        messageTone = AuthMessageTone.NOTICE,
                    )
                    startVerificationCodeCooldown()
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        isSendingVerificationCode = false,
                        message = error.toUiText(R.string.auth_error_code_send_failed),
                        messageTone = AuthMessageTone.ERROR,
                    )
                },
            )
        }
    }

    fun requestPasswordReset(email: String): Unit {
        if (mutableUiState.value.isBusy || email.isBlank()) {
            return
        }
        mutableUiState.value = mutableUiState.value.copy(
            isBusy = true,
            message = null,
            messageTone = AuthMessageTone.ERROR,
        )
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    api.requestPasswordReset(email)
                }
            }.fold(
                onSuccess = {
                    mutableUiState.value = mutableUiState.value.copy(
                        isBusy = false,
                        message = UiText.res(R.string.auth_msg_reset_sent),
                        messageTone = AuthMessageTone.NOTICE,
                    )
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        isBusy = false,
                        message = error.toUiText(R.string.auth_error_reset_failed),
                        messageTone = AuthMessageTone.ERROR,
                    )
                },
            )
        }
    }

    fun registerWithEmail(
        email: String,
        password: String,
        confirmPassword: String,
        verificationCode: String,
        displayName: String?,
        inviteCode: String,
    ): Unit {
        if (mutableUiState.value.providers?.inviteRequired == true && inviteCode.isBlank()) {
            mutableUiState.value = mutableUiState.value.copy(
                message = UiText.res(R.string.auth_error_invite_required),
                messageTone = AuthMessageTone.ERROR,
            )
            return
        }
        if (password != confirmPassword) {
            mutableUiState.value = mutableUiState.value.copy(
                message = UiText.res(R.string.auth_error_password_mismatch),
                messageTone = AuthMessageTone.ERROR,
            )
            return
        }
        if (
            verificationCode.length != 6 ||
            verificationCode.any { character -> !character.isDigit() }
        ) {
            mutableUiState.value = mutableUiState.value.copy(
                message = UiText.res(R.string.auth_error_code_required),
                messageTone = AuthMessageTone.ERROR,
            )
            return
        }
        submitEmailCredentials(
            email,
            password,
            confirmPassword,
            verificationCode,
            isRegistration = true,
            displayName = displayName,
            inviteCode = inviteCode,
        )
    }

    fun logout(): Unit {
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    api.logout()
                    tokenStore.clear()
                    repository.clearForLogout()
                    api.clearSession()
                }
            }.onFailure {
                tokenStore.clear()
                api.clearSession()
                repository.clearForLogout()
            }
            val providers = runCatching {
                withContext(Dispatchers.IO) { api.getAuthProviders() }
            }.getOrNull()
            mutableUiState.value = AuthUiState(
                status = AuthStatus.ANONYMOUS,
                providers = providers,
                message = if (providers == null) UiText.res(R.string.auth_msg_logged_out_no_providers) else null,
            )
        }
    }

    private fun restoreSession(): Unit {
        viewModelScope.launch {
            val token = tokenStore.loadToken()
            if (token == null) {
                loadAnonymousState()
                return@launch
            }
            runCatching {
                withContext(Dispatchers.IO) {
                    api.accessToken = token
                    val user = api.getCurrentUser()
                    repository.activateUser(user.id)
                    user
                }
            }.fold(
                onSuccess = { user ->
                    mutableUiState.value = AuthUiState(
                        status = AuthStatus.AUTHENTICATED,
                        user = user,
                    )
                },
                onFailure = {
                    tokenStore.clear()
                    api.clearSession()
                    loadAnonymousState(UiText.res(R.string.auth_error_session_expired))
                },
            )
        }
    }

    private fun submitEmailCredentials(
        email: String,
        password: String,
        confirmPassword: String,
        verificationCode: String,
        isRegistration: Boolean,
        displayName: String?,
        inviteCode: String = "",
    ): Unit {
        if (mutableUiState.value.isBusy || email.isBlank() || password.isBlank()) {
            return
        }
        mutableUiState.value = mutableUiState.value.copy(
            isBusy = true,
            message = null,
            messageTone = AuthMessageTone.ERROR,
        )
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    if (isRegistration) {
                        api.registerWithEmail(
                            email,
                            password,
                            confirmPassword,
                            verificationCode,
                            displayName,
                            inviteCode,
                        )
                    } else {
                        val session = api.loginWithEmail(email, password)
                        tokenStore.save(session.accessToken, session.user.id)
                        repository.activateUser(session.user.id)
                        session
                    }
                }
            }.fold(
                onSuccess = { result ->
                    if (result is AuthSession) {
                        mutableUiState.value = AuthUiState(
                            status = AuthStatus.AUTHENTICATED,
                            user = result.user,
                        )
                    } else {
                        result as EmailRegisterResponse
                        mutableUiState.value = mutableUiState.value.copy(
                            status = AuthStatus.ANONYMOUS,
                            isBusy = false,
                            message = UiText.res(R.string.auth_msg_registered),
                            messageTone = AuthMessageTone.NOTICE,
                        )
                    }
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        status = AuthStatus.ANONYMOUS,
                        isBusy = false,
                        message = error.toUiText(R.string.auth_error_email_login_failed),
                        messageTone = AuthMessageTone.ERROR,
                    )
                },
            )
        }
    }

    private fun startVerificationCodeCooldown(): Unit {
        verificationCodeCooldownJob?.cancel()
        verificationCodeCooldownJob = viewModelScope.launch {
            while (mutableUiState.value.verificationCodeCooldownSeconds > 0) {
                delay(1000)
                mutableUiState.value = mutableUiState.value.copy(
                    verificationCodeCooldownSeconds = (
                        mutableUiState.value.verificationCodeCooldownSeconds - 1
                    ).coerceAtLeast(0),
                )
            }
        }
    }

    private suspend fun loadAnonymousState(message: UiText? = null): Unit {
        val providers = runCatching {
            withContext(Dispatchers.IO) { api.getAuthProviders() }
        }.getOrNull()
        mutableUiState.value = AuthUiState(
            status = AuthStatus.ANONYMOUS,
            providers = providers,
            message = message ?: if (providers == null) {
                UiText.res(R.string.auth_error_server_unreachable)
            } else {
                null
            },
        )
    }

    companion object {
        const val MOBILE_REDIRECT_URI = "memoisle://auth/callback"

        fun factory(
            api: MemoApiClient,
            tokenStore: AuthTokenStore,
            repository: MemoRepository,
        ): ViewModelProvider.Factory {
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    require(modelClass.isAssignableFrom(AuthViewModel::class.java))
                    return AuthViewModel(api, tokenStore, repository) as T
                }
            }
        }
    }
}
