package com.memoisle.app

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.RELAY_MAX_FILE_BYTES
import com.memoisle.app.data.RELAY_WAIT_SECONDS
import com.memoisle.app.data.RelayItem
import com.memoisle.app.data.formatRelayBytes
import com.memoisle.app.data.relayFileError
import com.memoisle.app.data.relayTextError
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.MemoApiClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

data class RelayUiState(
    val items: List<RelayItem> = emptyList(),
    /** 每条内容在本机的过期时间（毫秒），首次收到时按服务端的剩余秒数算出。 */
    val deadlines: Map<String, Long> = emptyMap(),
    val sending: Boolean = false,
    val busyId: String? = null,
    val error: String? = null,
    val message: String? = null,
    /** 收件箱连接状态提示，例如断网重试中。 */
    val pollError: String? = null,
)

/**
 * 手机与网页互传文字或小文件。服务端只在内存里转发，取走即删，10 分钟内有效。
 * 界面可见期间循环长轮询收件箱；退出登录时 [reset]。
 */
class RelayViewModel(private val api: MemoApiClient) : ViewModel() {
    var uiState by mutableStateOf(RelayUiState())
        private set
    private var pollJob: Job? = null
    private var actionJob: Job? = null

    fun reset() {
        stopPolling()
        actionJob?.cancel()
        uiState = RelayUiState()
    }

    fun clearMessage() {
        uiState = uiState.copy(error = null, message = null)
    }

    fun showError(message: String) {
        uiState = uiState.copy(error = message, message = null)
    }

    fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch {
            var failures = 0
            while (isActive) {
                try {
                    val known = uiState.items.map { it.id }
                    val items = withContext(Dispatchers.IO) { api.pollRelayInbox(RELAY_WAIT_SECONDS, known) }
                    failures = 0
                    applyItems(items)
                    if (uiState.pollError != null) uiState = uiState.copy(pollError = null)
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    if (error is ApiException && error.statusCode == 401) {
                        uiState = uiState.copy(pollError = "登录已失效，请重新登录。")
                        return@launch
                    }
                    failures += 1
                    uiState = uiState.copy(pollError = "与服务器的连接中断，正在重试…")
                    delay((RETRY_BASE_MS * failures).coerceAtMost(RETRY_MAX_MS))
                }
            }
        }
    }

    fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    fun sendText(text: String, onDone: () -> Unit) {
        val problem = relayTextError(text)
        if (problem != null) {
            showError(problem)
            return
        }
        runAction(sending = true) {
            withContext(Dispatchers.IO) { api.sendRelayText(text) }
            onDone()
            uiState = uiState.copy(message = "文字已发给网页，10 分钟内在网页打开「传输」即可接收。")
        }
    }

    /** 读系统文件选择器选中的文件并发送；先查大小，超过 20 MB 不读入内存。 */
    fun sendFile(uri: Uri, contentResolver: ContentResolver) {
        runAction(sending = true) {
            val (name, size) = withContext(Dispatchers.IO) { queryNameAndSize(contentResolver, uri) }
            relayFileError(name, size)?.let { throw IllegalArgumentException(it) }
            val bytes = withContext(Dispatchers.IO) { readLimited(contentResolver, uri, name) }
            relayFileError(name, bytes.size.toLong())?.let { throw IllegalArgumentException(it) }
            val mimeType = contentResolver.getType(uri)
            withContext(Dispatchers.IO) { api.sendRelayFile(bytes, name, mimeType) }
            uiState = uiState.copy(message = "「$name」（${formatRelayBytes(bytes.size.toLong())}）已发给网页，10 分钟内有效。")
        }
    }

    /** 取走文件写进用户在 [uri] 选好的位置；失败时删掉空文件。 */
    fun saveFile(item: RelayItem, uri: Uri, contentResolver: ContentResolver) {
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            try {
                withContext(Dispatchers.IO) {
                    val output = contentResolver.openOutputStream(uri, "w")
                        ?: throw java.io.IOException("无法写入所选位置")
                    output.use { api.downloadRelayItem(item.id, it) }
                }
            } catch (error: Exception) {
                withContext(Dispatchers.IO) {
                    runCatching { DocumentsContract.deleteDocument(contentResolver, uri) }
                }
                throw error
            }
            removeLocal(item.id)
            uiState = uiState.copy(message = "已保存「${item.filename ?: "file"}」，服务端已删除这份内容。")
        }
    }

    /** 文本复制到剪贴板后从服务端移除；[copy] 由界面实现。 */
    fun copyText(item: RelayItem, copy: (String) -> Unit) {
        val text = item.text ?: return
        copy(text)
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            withContext(Dispatchers.IO) { api.discardRelayItem(item.id) }
            removeLocal(item.id)
            uiState = uiState.copy(message = "已复制到剪贴板，服务端已删除这段文字。")
        }
    }

    fun discard(item: RelayItem) {
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            withContext(Dispatchers.IO) { api.discardRelayItem(item.id) }
            removeLocal(item.id)
            uiState = uiState.copy(message = "已忽略。")
        }
    }

    private fun applyItems(items: List<RelayItem>) {
        val now = System.currentTimeMillis()
        val deadlines = items.associate { item ->
            item.id to (uiState.deadlines[item.id] ?: (now + item.expiresIn * 1_000L))
        }
        uiState = uiState.copy(items = items, deadlines = deadlines)
    }

    private fun removeLocal(id: String) {
        uiState = uiState.copy(
            items = uiState.items.filterNot { it.id == id },
            deadlines = uiState.deadlines - id,
        )
    }

    private fun runAction(
        sending: Boolean = false,
        busyId: String? = null,
        onNotFound: (() -> Unit)? = null,
        action: suspend () -> Unit,
    ) {
        if (uiState.sending || uiState.busyId != null) return
        uiState = uiState.copy(sending = sending, busyId = busyId, error = null, message = null)
        actionJob = viewModelScope.launch {
            try {
                action()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (error is ApiException && error.statusCode == 404 && onNotFound != null) {
                    onNotFound()
                    uiState = uiState.copy(error = "这份内容已被取走或已过期。")
                } else {
                    uiState = uiState.copy(error = describe(error))
                }
            } finally {
                uiState = uiState.copy(sending = false, busyId = null)
            }
        }
    }

    private fun queryNameAndSize(contentResolver: ContentResolver, uri: Uri): Pair<String, Long?> {
        val projection = arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        val row = runCatching {
            contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
                if (!cursor.moveToFirst()) return@use null
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                val name = if (nameIndex >= 0 && !cursor.isNull(nameIndex)) cursor.getString(nameIndex) else null
                val size = if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) cursor.getLong(sizeIndex) else null
                name to size
            }
        }.getOrNull()
        val name = row?.first?.takeIf { it.isNotBlank() } ?: uri.lastPathSegment ?: "file"
        return name to row?.second
    }

    /** 大小未知时边读边数，超过上限立刻停止，避免把大文件整个读进内存。 */
    private fun readLimited(contentResolver: ContentResolver, uri: Uri, name: String): ByteArray {
        val input = contentResolver.openInputStream(uri) ?: throw IllegalArgumentException("无法读取「$name」")
        return input.use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val read = stream.read(buffer)
                if (read < 0) break
                total += read
                if (total > RELAY_MAX_FILE_BYTES) {
                    throw IllegalArgumentException("「$name」超过 20 MB，单个文件不能超过 20 MB。")
                }
                output.write(buffer, 0, read)
            }
            output.toByteArray()
        }
    }

    private fun describe(error: Exception): String = when (error) {
        is ApiException -> error.detailMessage ?: "操作失败（${error.statusCode}），请重试。"
        is IllegalArgumentException -> error.message ?: "这个文件无法发送。"
        is java.io.IOException -> "无法连接服务器。传输需要在线使用，请检查网络后重试。"
        is SecurityException -> "没有读取或写入这个文件的权限。"
        else -> "传输失败，请稍后重试。"
    }

    override fun onCleared() {
        stopPolling()
        super.onCleared()
    }

    companion object {
        private const val RETRY_BASE_MS = 2_000L
        private const val RETRY_MAX_MS = 30_000L
        fun factory(api: MemoApiClient): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = RelayViewModel(api) as T
        }
    }
}
