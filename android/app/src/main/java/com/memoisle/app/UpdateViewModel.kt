package com.memoisle.app

import android.content.Context
import androidx.core.content.edit
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.AndroidRelease
import com.memoisle.app.data.shouldAutoCheck
import com.memoisle.app.data.shouldPromptRelease
import com.memoisle.app.update.AppUpdater
import com.memoisle.app.update.UpdateVerificationException
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class UpdatePhase {
    IDLE,
    CHECKING,
    AVAILABLE,
    DOWNLOADING,
    DOWNLOADED,
    FAILED,
    UP_TO_DATE,
}

data class UpdateUiState(
    val phase: UpdatePhase = UpdatePhase.IDLE,
    val release: AndroidRelease? = null,
    /** 下载进度 0..1；总大小未知时为 null。 */
    val progress: Float? = null,
    val downloadedFile: File? = null,
    /** 失败原因或「已是最新」提示。 */
    val message: String? = null,
    /** 下载刚完成，界面应自动打开一次系统安装器；打开后调用 [UpdateViewModel.installRequestHandled]。 */
    val installRequested: Boolean = false,
) {
    /** 更新对话框：有更新、下载中、已下载，或下载阶段失败。 */
    val showDialog: Boolean
        get() = release != null && when (phase) {
            UpdatePhase.AVAILABLE, UpdatePhase.DOWNLOADING, UpdatePhase.DOWNLOADED, UpdatePhase.FAILED -> true
            else -> false
        }

    /** 手动检查的结果用 Snackbar 提示：已是最新，或检查本身失败。 */
    val snackbarMessage: String?
        get() = message?.takeIf {
            phase == UpdatePhase.UP_TO_DATE || (phase == UpdatePhase.FAILED && release == null)
        }
}

/**
 * 检查与下载安卓端新版本。自动检查每 24 小时最多一次，静默失败；
 * 手动检查总会给出结果。下载完成后由界面调用 [AppUpdater.installIntent] 打开系统安装器。
 */
class UpdateViewModel(
    private val updater: AppUpdater,
    private val preferences: UpdatePreferences,
) : ViewModel() {
    private val _uiState = MutableStateFlow(UpdateUiState())
    val uiState: StateFlow<UpdateUiState> = _uiState.asStateFlow()
    private var checkJob: Job? = null
    private var downloadJob: Job? = null

    init {
        viewModelScope.launch { runCatching { updater.cleanup() } }
    }

    val currentVersionName: String get() = updater.currentVersionName

    /** 登录后调用；距上次检查不足 24 小时、或正在处理更新时什么都不做。 */
    fun autoCheck(nowMs: Long = System.currentTimeMillis()) {
        if (_uiState.value.phase != UpdatePhase.IDLE) return
        if (!shouldAutoCheck(preferences.lastCheckedAtMs, nowMs)) return
        check(manual = false, checkedAtMs = nowMs)
    }

    /** 菜单「检查更新」：忽略过的版本也会提示，结果总会告诉用户。 */
    fun manualCheck() {
        // 对话框打开期间菜单点不到；这里只挡住重复点击。
        if (_uiState.value.phase == UpdatePhase.CHECKING || _uiState.value.showDialog) return
        check(manual = true, checkedAtMs = System.currentTimeMillis())
    }

    private fun check(manual: Boolean, checkedAtMs: Long) {
        checkJob?.cancel()
        _uiState.value = UpdateUiState(phase = UpdatePhase.CHECKING)
        checkJob = viewModelScope.launch {
            val release = try {
                updater.fetchLatest()
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                _uiState.value = if (manual) {
                    UpdateUiState(phase = UpdatePhase.FAILED, message = "检查更新失败，请检查网络后重试")
                } else {
                    // 自动检查静默失败，不记时间，下次启动或登录再试。
                    UpdateUiState()
                }
                return@launch
            }
            // 请求成功（包括服务端还没发布）才算检查过，手动检查也会推迟下一次自动检查。
            preferences.lastCheckedAtMs = checkedAtMs
            val prompt = release != null && shouldPromptRelease(
                release = release,
                currentVersionCode = updater.currentVersionCode,
                ignoredVersionCode = preferences.ignoredVersionCode,
                manual = manual,
            )
            _uiState.value = when {
                prompt -> UpdateUiState(phase = UpdatePhase.AVAILABLE, release = release)
                manual -> UpdateUiState(
                    phase = UpdatePhase.UP_TO_DATE,
                    message = "已是最新版本（${updater.currentVersionName}）",
                )
                else -> UpdateUiState()
            }
        }
    }

    fun startDownload() {
        val release = _uiState.value.release ?: return
        if (_uiState.value.phase == UpdatePhase.DOWNLOADING) return
        downloadJob?.cancel()
        _uiState.update { it.copy(phase = UpdatePhase.DOWNLOADING, progress = 0f, message = null) }
        downloadJob = viewModelScope.launch {
            try {
                val file = updater.download(release) { downloaded, total ->
                    val progress = if (total > 0) (downloaded.toFloat() / total).coerceIn(0f, 1f) else null
                    // 每 1% 刷新一次，避免下载线程频繁触发重组。
                    _uiState.update { state ->
                        val previous = state.progress
                        if (state.phase != UpdatePhase.DOWNLOADING) {
                            state
                        } else if (progress == null || previous == null || progress - previous >= 0.01f || progress >= 1f) {
                            state.copy(progress = progress)
                        } else {
                            state
                        }
                    }
                }
                _uiState.update {
                    it.copy(
                        phase = UpdatePhase.DOWNLOADED,
                        progress = 1f,
                        downloadedFile = file,
                        installRequested = true,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: UpdateVerificationException) {
                fail(error.message ?: "安装包校验失败")
            } catch (_: Exception) {
                fail("下载失败，请检查网络后重试")
            }
        }
    }

    private fun fail(message: String) {
        _uiState.update {
            it.copy(
                phase = UpdatePhase.FAILED,
                progress = null,
                downloadedFile = null,
                message = message,
                installRequested = false,
            )
        }
    }

    fun installRequestHandled() {
        _uiState.update { it.copy(installRequested = false) }
    }

    /** 系统没有能处理安装包的界面等情况；重试会复用已校验的文件。 */
    fun reportInstallFailure() {
        fail("无法打开系统安装界面，请稍后重试")
    }

    /** 「稍后」：关闭对话框，正在下载就取消（临时文件随之删除）。 */
    fun dismiss() {
        downloadJob?.cancel()
        _uiState.value = UpdateUiState()
    }

    /** 「忽略此版本」：之后自动检查不再提示这个 versionCode，手动检查仍会提示。 */
    fun ignoreRelease() {
        _uiState.value.release?.let { preferences.ignoredVersionCode = it.versionCode }
        dismiss()
    }

    /** Snackbar 已经展示过手动检查的结果。 */
    fun messageShown() {
        if (_uiState.value.snackbarMessage != null) {
            _uiState.value = UpdateUiState()
        }
    }

    companion object {
        fun factory(context: Context, updater: AppUpdater): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    UpdateViewModel(updater, UpdatePreferences(context.applicationContext)) as T
            }
    }
}

/** 自动检查时间和忽略的版本只存本机，退出登录也保留。 */
class UpdatePreferences(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    var lastCheckedAtMs: Long
        get() = preferences.getLong(KEY_LAST_CHECKED_AT, 0L)
        set(value) = preferences.edit { putLong(KEY_LAST_CHECKED_AT, value) }

    var ignoredVersionCode: Int?
        get() = preferences.getInt(KEY_IGNORED_VERSION_CODE, 0).takeIf { it > 0 }
        set(value) = preferences.edit {
            if (value == null) remove(KEY_IGNORED_VERSION_CODE) else putInt(KEY_IGNORED_VERSION_CODE, value)
        }

    private companion object {
        const val PREFERENCES_NAME = "memoisle_updates"
        const val KEY_LAST_CHECKED_AT = "last_checked_at"
        const val KEY_IGNORED_VERSION_CODE = "ignored_version_code"
    }
}
