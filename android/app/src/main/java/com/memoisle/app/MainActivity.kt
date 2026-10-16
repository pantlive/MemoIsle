package com.memoisle.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import com.memoisle.app.sync.MemoSyncScheduler
import com.memoisle.app.ui.AuthScreen
import com.memoisle.app.ui.MemoHomeScreen
import com.memoisle.app.ui.MemoIsleTheme

class MainActivity : ComponentActivity() {
    private val authViewModel: AuthViewModel by viewModels {
        val application = application as MemoIsleApplication
        AuthViewModel.factory(
            application.api,
            application.tokenStore,
            application.repository,
        )
    }
    private val viewModel: MemoViewModel by viewModels {
        MemoViewModel.factory((application as MemoIsleApplication).repository)
    }
    private val vaultViewModel: VaultViewModel by viewModels {
        VaultViewModel.factory((application as MemoIsleApplication).api)
    }
    private var sharedText by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedText = extractSharedText(intent)
        extractAuthToken(intent)?.let(authViewModel::completeLogin)
        enableEdgeToEdge()
        setContent {
            val authState by authViewModel.uiState.collectAsState()
            val context = LocalContext.current
            val uriHandler = LocalUriHandler.current
            LaunchedEffect(authState.status, authState.user?.id) {
                if (authState.status == AuthStatus.AUTHENTICATED) {
                    // 每次登录（包括退出后重新登录）都重新拉取当前账号的数据。
                    MemoSyncScheduler.schedule(context)
                    viewModel.refresh()
                } else if (authState.status == AuthStatus.ANONYMOUS) {
                    MemoSyncScheduler.cancel(context)
                    // 退出登录后内存里不留解锁后的库密钥。
                    vaultViewModel.reset()
                }
            }
            MemoIsleTheme {
                when (authState.status) {
                    AuthStatus.AUTHENTICATED -> MemoHomeScreen(
                        viewModel = viewModel,
                        vaultViewModel = vaultViewModel,
                        sharedText = sharedText,
                        onSharedTextConsumed = { sharedText = null },
                        onLogout = authViewModel::logout,
                    )
                    AuthStatus.LOADING, AuthStatus.ANONYMOUS -> AuthScreen(
                        viewModel = authViewModel,
                        onOpenProvider = { provider ->
                            uriHandler.openUri(authViewModel.authorizationUrl(provider))
                        },
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        sharedText = extractSharedText(intent)
        extractAuthToken(intent)?.let(authViewModel::completeLogin)
    }

    private fun extractSharedText(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_SEND || intent.type != "text/plain") {
            return null
        }
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()?.ifEmpty { null }
    }

    private fun extractAuthToken(intent: Intent?): String? {
        val data: Uri = intent?.data ?: return null
        if (data.scheme != "memoisle" || data.host != "auth" || data.path != "/callback") {
            return null
        }
        val fragment = data.fragment ?: return null
        return fragment.split("&")
            .firstOrNull { it.startsWith("access_token=") }
            ?.substringAfter("=")
            ?.takeIf { it.isNotBlank() }
    }
}
