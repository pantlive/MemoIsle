package com.memoisle.app

import android.content.ActivityNotFoundException
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
import com.memoisle.app.ui.UpdateDialog
import com.memoisle.app.update.AppUpdater
import java.io.File

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
    private val ledgerViewModel: LedgerViewModel by viewModels {
        LedgerViewModel.factory((application as MemoIsleApplication).api)
    }
    private val relayViewModel: RelayViewModel by viewModels {
        RelayViewModel.factory((application as MemoIsleApplication).api)
    }
    private val forgetViewModel: ForgetViewModel by viewModels {
        ForgetViewModel.factory((application as MemoIsleApplication).api)
    }
    private val appUpdater: AppUpdater by lazy {
        AppUpdater(applicationContext, (application as MemoIsleApplication).api)
    }
    private val updateViewModel: UpdateViewModel by viewModels {
        UpdateViewModel.factory(applicationContext, appUpdater)
    }
    private var sharedText by mutableStateOf<String?>(null)

    /** 去系统设置授权「安装未知应用」后回来，自动继续安装。 */
    private var installAfterPermission = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedText = extractSharedText(intent)
        extractAuthToken(intent)?.let(authViewModel::completeLogin)
        enableEdgeToEdge()
        setContent {
            val authState by authViewModel.uiState.collectAsState()
            val updateState by updateViewModel.uiState.collectAsState()
            val context = LocalContext.current
            val uriHandler = LocalUriHandler.current
            LaunchedEffect(authState.status, authState.user?.id) {
                if (authState.status == AuthStatus.AUTHENTICATED) {
                    // 每次登录（包括退出后重新登录）都重新拉取当前账号的数据。
                    MemoSyncScheduler.schedule(context)
                    viewModel.refresh()
                    // 只有正式包自动检查更新；debug 包包名不同，也装不上正式包。
                    if (!BuildConfig.DEBUG) {
                        updateViewModel.autoCheck()
                    }
                } else if (authState.status == AuthStatus.ANONYMOUS) {
                    MemoSyncScheduler.cancel(context)
                    // 退出登录后内存里不留解锁后的库密钥。
                    vaultViewModel.reset()
                    ledgerViewModel.reset()
                    relayViewModel.reset()
                    forgetViewModel.reset()
                    updateViewModel.dismiss()
                }
            }
            LaunchedEffect(updateState.installRequested) {
                if (updateState.installRequested) {
                    updateViewModel.installRequestHandled()
                    updateState.downloadedFile?.let(::installUpdate)
                }
            }
            MemoIsleTheme {
                when (authState.status) {
                    AuthStatus.AUTHENTICATED -> MemoHomeScreen(
                        viewModel = viewModel,
                        vaultViewModel = vaultViewModel,
                        ledgerViewModel = ledgerViewModel,
                        relayViewModel = relayViewModel,
                        forgetViewModel = forgetViewModel,
                        sharedText = sharedText,
                        onSharedTextConsumed = { sharedText = null },
                        onLogout = authViewModel::logout,
                        updateCheckMessage = updateState.snackbarMessage,
                        isCheckingUpdate = updateState.phase == UpdatePhase.CHECKING,
                        onCheckUpdate = updateViewModel::manualCheck,
                        onUpdateMessageShown = updateViewModel::messageShown,
                    )
                    AuthStatus.LOADING, AuthStatus.ANONYMOUS -> AuthScreen(
                        viewModel = authViewModel,
                        onOpenProvider = { provider ->
                            uriHandler.openUri(authViewModel.authorizationUrl(provider))
                        },
                    )
                }
                if (authState.status == AuthStatus.AUTHENTICATED && updateState.showDialog) {
                    UpdateDialog(
                        state = updateState,
                        currentVersionName = BuildConfig.VERSION_NAME,
                        onUpdate = updateViewModel::startDownload,
                        onInstall = { updateState.downloadedFile?.let(::installUpdate) },
                        onLater = updateViewModel::dismiss,
                        onIgnore = updateViewModel::ignoreRelease,
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (installAfterPermission && appUpdater.canRequestPackageInstalls()) {
            installAfterPermission = false
            val state = updateViewModel.uiState.value
            if (state.phase == UpdatePhase.DOWNLOADED) {
                state.downloadedFile?.let(::installUpdate)
            }
        }
    }

    /** 没有安装未知应用权限时先跳到系统设置；有权限则交给系统安装器，由用户确认。 */
    private fun installUpdate(apk: File) {
        if (!apk.isFile) {
            updateViewModel.reportInstallFailure()
            return
        }
        if (!appUpdater.canRequestPackageInstalls()) {
            installAfterPermission = true
            try {
                startActivity(appUpdater.unknownSourcesSettingsIntent())
            } catch (_: ActivityNotFoundException) {
                installAfterPermission = false
                updateViewModel.reportInstallFailure()
            }
            return
        }
        try {
            startActivity(appUpdater.installIntent(apk))
        } catch (_: ActivityNotFoundException) {
            updateViewModel.reportInstallFailure()
        } catch (_: IllegalArgumentException) {
            // FileProvider 未开放该目录时抛出；正常不会发生。
            updateViewModel.reportInstallFailure()
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
