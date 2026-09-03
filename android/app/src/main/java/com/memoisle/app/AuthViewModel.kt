package com.memoisle.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.AuthTokenStore
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.network.AuthProvidersResponse
import com.memoisle.app.network.AuthUser
import com.memoisle.app.network.MemoApiClient
import kotlinx.coroutines.Dispatchers
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

data class AuthUiState(
    val status: AuthStatus = AuthStatus.LOADING,
    val user: AuthUser? = null,
    val providers: AuthProvidersResponse? = null,
    val message: String? = null,
    val isBusy: Boolean = false,
)

class AuthViewModel(
    private val api: MemoApiClient,
    private val tokenStore: AuthTokenStore,
    private val repository: MemoRepository,
) : ViewModel() {
    private val mutableUiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = mutableUiState.asStateFlow()

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
                    )
                },
            )
        }
    }

    fun loginWithEmail(email: String, password: String): Unit {
        submitEmailCredentials(email, password, password, isRegistration = false, displayName = null)
    }

    fun registerWithEmail(
        email: String,
        password: String,
        confirmPassword: String,
        displayName: String?,
    ): Unit {
        if (password != confirmPassword) {
            mutableUiState.value = mutableUiState.value.copy(
                message = "两次输入的密码不一致",
            )
            return
        }
        submitEmailCredentials(
            email,
            password,
            confirmPassword,
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
            val providers = withContext(Dispatchers.IO) { api.getAuthProviders() }
            mutableUiState.value = AuthUiState(
                status = AuthStatus.ANONYMOUS,
                providers = providers,
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
        isRegistration: Boolean,
        displayName: String?,
    ): Unit {
        if (mutableUiState.value.isBusy || email.isBlank() || password.isBlank()) {
            return
        }
        mutableUiState.value = mutableUiState.value.copy(isBusy = true, message = null)
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val session = if (!isRegistration) {
                        api.loginWithEmail(email, password)
                    } else {
                        api.registerWithEmail(email, password, confirmPassword, displayName)
                    }
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
                        message = error.message ?: "邮箱登录失败，请稍后重试",
                    )
                },
            )
        }
    }

    private suspend fun loadAnonymousState(message: String? = null): Unit {
        val providers = withContext(Dispatchers.IO) { api.getAuthProviders() }
        mutableUiState.value = AuthUiState(
            status = AuthStatus.ANONYMOUS,
            providers = providers,
            message = message,
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
