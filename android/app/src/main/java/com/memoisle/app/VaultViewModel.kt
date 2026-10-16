package com.memoisle.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.VaultCrypto
import com.memoisle.app.data.VaultDecryptException
import com.memoisle.app.data.VaultEntry
import com.memoisle.app.data.VaultItemData
import com.memoisle.app.data.VaultKeyMaterial
import com.memoisle.app.data.WrongMasterPasswordException
import com.memoisle.app.data.stampSecretChange
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.network.VaultItemRecord
import java.util.UUID
import javax.crypto.SecretKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class VaultPhase { LOADING, ERROR, NOT_CONFIGURED, LOCKED, UNLOCKED }

data class VaultUiState(
    val phase: VaultPhase = VaultPhase.LOADING,
    val itemCount: Int = 0,
    val entries: List<VaultEntry> = emptyList(),
    val brokenCount: Int = 0,
    val busy: Boolean = false,
    val error: String? = null,
    val message: String? = null,
)

/**
 * 手机端密码库：解锁后的库密钥只放在内存里，五分钟无操作、App 退到后台或退出登录都会锁定。
 * 设置主密码、更改主密码和加密备份仍在网页端完成。
 */
class VaultViewModel(
    private val api: MemoApiClient,
) : ViewModel() {
    var uiState by mutableStateOf(VaultUiState())
        private set

    /** 上次解锁时需要处理的提醒数，锁定后底部导航仍显示；退出登录时清零。 */
    var lastReminderCount by mutableIntStateOf(0)
        private set
    private var key: SecretKey? = null
    private var material: VaultKeyMaterial? = null
    private var lockJob: Job? = null

    fun load() {
        uiState = uiState.copy(phase = if (key != null) uiState.phase else VaultPhase.LOADING, error = null)
        viewModelScope.launch {
            try {
                val status = withContext(Dispatchers.IO) { api.getVaultStatus() }
                if (!status.configured) {
                    lock()
                    uiState = uiState.copy(phase = VaultPhase.NOT_CONFIGURED)
                    return@launch
                }
                material = VaultKeyMaterial(
                    kdf = status.kdf.orEmpty(),
                    iterations = status.kdfIterations ?: 0,
                    salt = status.kdfSalt.orEmpty(),
                    wrappedKey = status.wrappedKey.orEmpty(),
                    wrapIv = status.wrapIv.orEmpty(),
                )
                if (key != null) {
                    reloadEntries()
                } else {
                    uiState = uiState.copy(phase = VaultPhase.LOCKED, itemCount = status.itemCount)
                }
            } catch (error: Exception) {
                uiState = uiState.copy(phase = VaultPhase.ERROR, error = describe(error))
            }
        }
    }

    fun unlock(password: String) {
        if (password.isEmpty() || uiState.busy) return
        uiState = uiState.copy(busy = true, error = null)
        viewModelScope.launch {
            try {
                // 每次解锁都取最新参数，主密码可能刚在网页端改过。
                val status = withContext(Dispatchers.IO) { api.getVaultStatus() }
                if (!status.configured) {
                    uiState = uiState.copy(phase = VaultPhase.NOT_CONFIGURED, busy = false)
                    return@launch
                }
                val latest = VaultKeyMaterial(
                    kdf = status.kdf.orEmpty(),
                    iterations = status.kdfIterations ?: 0,
                    salt = status.kdfSalt.orEmpty(),
                    wrappedKey = status.wrappedKey.orEmpty(),
                    wrapIv = status.wrapIv.orEmpty(),
                )
                material = latest
                key = withContext(Dispatchers.Default) { VaultCrypto.unlock(password, latest) }
                reloadEntries()
                uiState = uiState.copy(busy = false, message = "已解锁，5 分钟无操作或 App 退到后台会自动锁定。")
                touch()
            } catch (error: Exception) {
                uiState = uiState.copy(busy = false, error = describe(error))
            }
        }
    }

    fun lock() {
        lockJob?.cancel()
        lockJob = null
        if (key == null) return
        key = null
        uiState = uiState.copy(
            phase = if (uiState.phase == VaultPhase.UNLOCKED) VaultPhase.LOCKED else uiState.phase,
            entries = emptyList(),
            brokenCount = 0,
            message = "密码库已锁定。",
        )
    }

    /** 用户在密码库里有操作时顺延自动锁定。 */
    fun touch() {
        if (key == null) return
        lockJob?.cancel()
        lockJob = viewModelScope.launch {
            delay(AUTO_LOCK_MS)
            lock()
        }
    }

    fun rememberReminderCount(count: Int) {
        if (key != null) lastReminderCount = count
    }

    /** 退出登录：锁定并忘掉提醒数。 */
    fun reset() {
        lock()
        lastReminderCount = 0
        uiState = VaultUiState()
    }

    fun clearMessage() {
        uiState = uiState.copy(message = null, error = null)
    }

    fun showMessage(message: String) {
        uiState = uiState.copy(message = message)
    }

    fun save(entry: VaultEntry?, data: VaultItemData, onDone: () -> Unit) {
        val currentKey = key ?: return
        if (uiState.busy) return
        uiState = uiState.copy(busy = true, error = null)
        viewModelScope.launch {
            val id = entry?.id ?: UUID.randomUUID().toString()
            try {
                val stamped = stampSecretChange(entry?.data, data)
                val (iv, ciphertext) = withContext(Dispatchers.Default) {
                    VaultCrypto.encryptItem(currentKey, id, stamped.toJson().toByteArray(Charsets.UTF_8))
                }
                val record = withContext(Dispatchers.IO) {
                    if (entry == null) {
                        api.createVaultItem(id, iv, ciphertext)
                    } else {
                        api.updateVaultItem(id, iv, ciphertext, entry.version)
                    }
                }
                val saved = decrypt(currentKey, record)
                uiState = uiState.copy(
                    busy = false,
                    entries = listOf(saved) + uiState.entries.filter { it.id != saved.id },
                    message = "已加密保存「${saved.data.title}」。",
                )
                onDone()
            } catch (error: ApiException) {
                if (error.statusCode == 409) {
                    reloadEntries()
                    uiState = uiState.copy(busy = false, error = "这一条刚在别处修改过，已刷新列表，请重新打开后修改。")
                    onDone()
                } else {
                    uiState = uiState.copy(busy = false, error = describe(error))
                }
            } catch (error: Exception) {
                uiState = uiState.copy(busy = false, error = describe(error))
            }
        }
    }

    fun delete(entry: VaultEntry, onDone: () -> Unit) {
        if (key == null || uiState.busy) return
        uiState = uiState.copy(busy = true, error = null)
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { api.deleteVaultItem(entry.id, entry.version) }
                uiState = uiState.copy(
                    busy = false,
                    entries = uiState.entries.filter { it.id != entry.id },
                    message = "已删除「${entry.data.title}」。",
                )
                onDone()
            } catch (error: ApiException) {
                uiState = uiState.copy(
                    busy = false,
                    error = if (error.statusCode == 409) "这一条刚在别处修改过，请刷新后再删除。" else describe(error),
                )
            } catch (error: Exception) {
                uiState = uiState.copy(busy = false, error = describe(error))
            }
        }
    }

    private suspend fun reloadEntries() {
        val currentKey = key ?: return
        val records = withContext(Dispatchers.IO) { api.listVaultItems() }
        val decrypted = withContext(Dispatchers.Default) {
            records.mapNotNull { record -> runCatching { decrypt(currentKey, record) }.getOrNull() }
        }
        uiState = uiState.copy(
            phase = VaultPhase.UNLOCKED,
            entries = decrypted,
            brokenCount = records.size - decrypted.size,
            itemCount = records.size,
        )
    }

    private fun decrypt(currentKey: SecretKey, record: VaultItemRecord): VaultEntry {
        val plaintext = VaultCrypto.decryptItem(currentKey, record.id, record.iv, record.ciphertext)
        return VaultEntry(
            id = record.id,
            version = record.version,
            createdAt = record.createdAt,
            data = VaultItemData.fromJson(plaintext.toString(Charsets.UTF_8)),
        )
    }

    private fun describe(error: Exception): String = when (error) {
        is WrongMasterPasswordException -> error.message.orEmpty()
        is VaultDecryptException -> error.message.orEmpty()
        is ApiException -> error.detailMessage ?: "操作失败（${error.statusCode}），请稍后重试。"
        is java.io.IOException -> "无法连接服务器，请检查网络后重试。"
        else -> error.message?.takeIf { it.isNotBlank() } ?: "操作失败，请稍后重试。"
    }

    override fun onCleared() {
        key = null
        super.onCleared()
    }

    companion object {
        const val AUTO_LOCK_MS = 5 * 60_000L

        fun factory(api: MemoApiClient): ViewModelProvider.Factory {
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return VaultViewModel(api) as T
                }
            }
        }
    }
}
