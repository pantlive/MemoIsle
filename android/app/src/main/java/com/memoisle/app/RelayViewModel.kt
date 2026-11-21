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
import com.memoisle.app.data.relayImageExtension
import com.memoisle.app.data.relayTextError
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.ui.HasUiText
import com.memoisle.app.ui.UiText
import com.memoisle.app.ui.UiTextException
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class RelayUiState(
    val items: List<RelayItem> = emptyList(),
    /** 每条内容在本机的过期时间（毫秒），首次收到时按服务端的剩余秒数算出。 */
    val deadlines: Map<String, Long> = emptyMap(),
    val sending: Boolean = false,
    val busyId: String? = null,
    val error: UiText? = null,
    val message: UiText? = null,
    /** 收件箱连接状态提示，例如断网重试中。 */
    val pollError: UiText? = null,
)

/**
 * 手机与网页互传文字、图片或小文件。服务端只在内存里转发，取走即删，10 分钟内有效。
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

    fun showError(message: UiText) {
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
                        uiState = uiState.copy(pollError = UiText.res(R.string.relay_poll_session_expired))
                        return@launch
                    }
                    failures += 1
                    uiState = uiState.copy(pollError = UiText.res(R.string.relay_poll_reconnecting))
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
            uiState = uiState.copy(message = UiText.res(R.string.relay_msg_text_sent))
        }
    }

    /** 读系统文件选择器选中的文件并发送；先查大小，超过 20 MB 不读入内存。 */
    fun sendFile(uri: Uri, contentResolver: ContentResolver, fallbackName: String? = null) {
        runAction(sending = true) {
            val (queriedName, size) = withContext(Dispatchers.IO) { queryNameAndSize(contentResolver, uri) }
            val name = resolveFileName(queriedName, fallbackName)
            relayFileError(name, size)?.let { throw UiTextException(it) }
            val bytes = withContext(Dispatchers.IO) { readLimited(contentResolver, uri, name) }
            relayFileError(name, bytes.size.toLong())?.let { throw UiTextException(it) }
            val queriedMime = contentResolver.getType(uri)?.ifBlank { null }
            val mimeType = when {
                queriedMime?.startsWith("image/") == true -> queriedMime
                else -> mimeFromFileName(name) ?: queriedMime
            }
            withContext(Dispatchers.IO) { api.sendRelayFile(bytes, name, mimeType) }
            uiState = uiState.copy(message = UiText.res(R.string.relay_msg_file_sent, name, formatRelayBytes(bytes.size.toLong())))
        }
    }

    /** 取走文件写进用户在 [uri] 选好的位置；失败时删掉空文件。 */
    fun saveFile(item: RelayItem, uri: Uri, contentResolver: ContentResolver) {
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            try {
                withContext(Dispatchers.IO) {
                    val output = contentResolver.openOutputStream(uri, "w")
                        ?: throw java.io.IOException("Cannot write to the selected location")
                    output.use { api.downloadRelayItem(item.id, it) }
                }
            } catch (error: Exception) {
                withContext(Dispatchers.IO) {
                    runCatching { DocumentsContract.deleteDocument(contentResolver, uri) }
                }
                throw error
            }
            removeLocal(item.id)
            uiState = uiState.copy(message = UiText.res(R.string.relay_msg_file_saved, item.filename ?: "file"))
        }
    }

    /**
     * 把图片下载到 [cacheDir]/relay_clipboard/，取走即删。
     * 写入前清掉该目录旧文件。成功后 [onReady] 把文件交给界面写入系统剪贴板。
     */
    fun copyImage(item: RelayItem, cacheDir: File, onReady: (File) -> Unit) {
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            val file = withContext(Dispatchers.IO) { writeClipboardCache(cacheDir, item) }
            removeLocal(item.id)
            onReady(file)
            if (uiState.error == null) {
                uiState = uiState.copy(message = UiText.res(R.string.relay_msg_image_copied))
            }
        }
    }

    /** 剪贴板写入失败时，把已经取走的本地文件保存到用户选的位置。 */
    fun saveCachedFile(file: File, uri: Uri, contentResolver: ContentResolver, displayName: String) {
        runAction {
            try {
                withContext(Dispatchers.IO) {
                    val output = contentResolver.openOutputStream(uri, "w")
                        ?: throw java.io.IOException("Cannot write to the selected location")
                    output.use { out -> file.inputStream().use { input -> input.copyTo(out) } }
                }
            } catch (error: Exception) {
                withContext(Dispatchers.IO) {
                    runCatching { DocumentsContract.deleteDocument(contentResolver, uri) }
                }
                throw error
            }
            uiState = uiState.copy(message = UiText.res(R.string.relay_msg_clipboard_failed_saved, displayName))
        }
    }

    /** 文本复制到剪贴板后从服务端移除；[copy] 由界面实现。 */
    fun copyText(item: RelayItem, copy: (String) -> Unit) {
        val text = item.text ?: return
        copy(text)
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            withContext(Dispatchers.IO) { api.discardRelayItem(item.id) }
            removeLocal(item.id)
            uiState = uiState.copy(message = UiText.res(R.string.relay_msg_text_copied))
        }
    }

    fun discard(item: RelayItem) {
        runAction(busyId = item.id, onNotFound = { removeLocal(item.id) }) {
            withContext(Dispatchers.IO) { api.discardRelayItem(item.id) }
            removeLocal(item.id)
            uiState = uiState.copy(message = UiText.res(R.string.relay_msg_dismissed))
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
                    uiState = uiState.copy(error = UiText.res(R.string.relay_error_gone))
                } else {
                    uiState = uiState.copy(error = describe(error))
                }
            } finally {
                uiState = uiState.copy(sending = false, busyId = null)
            }
        }
    }

    private fun resolveFileName(queriedName: String, fallbackName: String?): String {
        if (fallbackName.isNullOrBlank()) return queriedName.ifBlank { "file" }
        if (queriedName.isBlank() || queriedName == "file") return fallbackName
        val dot = queriedName.lastIndexOf('.')
        if (dot <= 0 || dot == queriedName.lastIndex) return fallbackName
        return queriedName
    }

    private fun mimeFromFileName(name: String): String? = when (
        name.substringAfterLast('.', "").lowercase(Locale.ROOT)
    ) {
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        "gif" -> "image/gif"
        "webp" -> "image/webp"
        "bmp" -> "image/bmp"
        "svg" -> "image/svg+xml"
        "heic" -> "image/heic"
        "heif" -> "image/heif"
        else -> null
    }

    private fun writeClipboardCache(cacheDir: File, item: RelayItem): File {
        val directory = File(cacheDir, CLIPBOARD_DIRECTORY)
        if (!directory.exists() && !directory.mkdirs() && !directory.isDirectory) {
            throw java.io.IOException("Cannot prepare the clipboard cache directory")
        }
        directory.listFiles()?.forEach { old -> old.delete() }
        val target = File(directory, "${item.id}.${relayImageExtension(item.mimeType)}")
        try {
            target.outputStream().use { api.downloadRelayItem(item.id, it) }
        } catch (error: Exception) {
            target.delete()
            throw error
        }
        return target
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
        val input = contentResolver.openInputStream(uri) ?: throw UiTextException(UiText.res(R.string.relay_error_cannot_read, name))
        return input.use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val read = stream.read(buffer)
                if (read < 0) break
                total += read
                if (total > RELAY_MAX_FILE_BYTES) {
                    throw UiTextException(UiText.res(R.string.relay_error_file_over_limit, name))
                }
                output.write(buffer, 0, read)
            }
            output.toByteArray()
        }
    }

    private fun describe(error: Exception): UiText = when (error) {
        is HasUiText -> error.text
        is ApiException -> error.detailMessage?.let(UiText::plain)
            ?: UiText.res(R.string.error_operation_failed_retry, error.statusCode)
        is IllegalArgumentException -> error.message?.let(UiText::plain) ?: UiText.res(R.string.relay_error_cannot_send)
        is java.io.IOException -> UiText.res(R.string.relay_error_offline)
        is SecurityException -> UiText.res(R.string.relay_error_permission)
        else -> UiText.res(R.string.relay_error_generic)
    }

    override fun onCleared() {
        stopPolling()
        super.onCleared()
    }

    companion object {
        private const val RETRY_BASE_MS = 2_000L
        private const val RETRY_MAX_MS = 30_000L
        const val CLIPBOARD_DIRECTORY = "relay_clipboard"
        fun factory(api: MemoApiClient): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = RelayViewModel(api) as T
        }
    }
}
