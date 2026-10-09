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
    val message: String? = null,
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
                    api.accessToken = null
                    loadAnonymousState(error.message ?: "登录失败，请重新尝试")
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
                        message = error.message ?: "登录失败，请稍后重试",
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

    fun requestVerificationCode(email: String): Unit {
        val state = mutableUiState.value
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
                    api.requestVerificationCode(email)
                }
            }.fold(
                onSuccess = {
                    mutableUiState.value = mutableUiState.value.copy(
                        isSendingVerificationCode = false,
                        verificationCodeCooldownSeconds = 60,
                        message = "验证码已发送，请查收邮箱（10 分钟内有效）。",
                        messageTone = AuthMessageTone.NOTICE,
                    )
                    startVerificationCodeCooldown()
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        isSendingVerificationCode = false,
                        message = error.message ?: "验证码发送失败，请稍后重试",
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
                        message = "如果邮箱已注册，重置链接已发送，请查收邮件。",
                        messageTone = AuthMessageTone.NOTICE,
                    )
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        isBusy = false,
                        message = error.message ?: "重置链接发送失败，请稍后重试",
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
    ): Unit {
        if (password != confirmPassword) {
            mutableUiState.value = mutableUiState.value.copy(
                message = "两次输入的密码不一致",
                messageTone = AuthMessageTone.ERROR,
            )
            return
        }
        if (
            verificationCode.length != 6 ||
            verificationCode.any { character -> !character.isDigit() }
        ) {
            mutableUiState.value = mutableUiState.value.copy(
                message = "请输入 6 位邮箱验证码",
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
        )
    }

    fun logout(): Unit {
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    api.logout()
                    tokenStore.clear()
                    repository.clearForLogout()
                    api.accessToken = null
                }
            }.onFailure {
                tokenStore.clear()
                api.accessToken = null
                repository.clearForLogout()
            }
            val providers = runCatching {
                withContext(Dispatchers.IO) { api.getAuthProviders() }
            }.getOrNull()
            mutableUiState.value = AuthUiState(
                status = AuthStatus.ANONYMOUS,
                providers = providers,
                message = if (providers == null) "已退出登录，当前无法读取登录方式" else null,
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
                    api.accessToken = null
                    loadAnonymousState("登录已过期，请重新登录")
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
                            message = "注册成功，请使用邮箱登录。",
                            messageTone = AuthMessageTone.NOTICE,
                        )
                    }
                },
                onFailure = { error ->
                    mutableUiState.value = mutableUiState.value.copy(
                        status = AuthStatus.ANONYMOUS,
                        isBusy = false,
                        message = error.message ?: "邮箱登录失败，请稍后重试",
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

    private suspend fun loadAnonymousState(message: String? = null): Unit {
        val providers = runCatching {
            withContext(Dispatchers.IO) { api.getAuthProviders() }
        }.getOrNull()
        mutableUiState.value = AuthUiState(
            status = AuthStatus.ANONYMOUS,
            providers = providers,
            message = message ?: if (providers == null) {
                "当前无法连接服务端，请检查网络后重试"
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
