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
import com.memoisle.app.data.FORGET_MAX_ATTACHMENTS
import com.memoisle.app.data.FORGET_MAX_ATTACHMENT_BYTES
import com.memoisle.app.data.FORGET_PREVIEW_MAX_BYTES
import com.memoisle.app.data.ForgetItem
import com.memoisle.app.data.ForgetItemInput
import com.memoisle.app.data.forgetFileError
import com.memoisle.app.data.forgetTextError
import com.memoisle.app.data.isForgetImage
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.ui.HasUiText
import com.memoisle.app.ui.UiText
import com.memoisle.app.ui.UiTextException
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class ForgetUiState(
    val query: String = "",
    val items: List<ForgetItem> = emptyList(),
    val loading: Boolean = false,
    val busy: Boolean = false,
    val error: UiText? = null,
    val message: UiText? = null,
    /** 冲突后加一，界面用它把编辑框刷回服务端文字。 */
    val textEpoch: Int = 0,
    val previews: Map<String, ByteArray> = emptyMap(),
    val previewNotes: Map<String, UiText> = emptyMap(),
)

/** 在线易忘事项。不写入本地数据库；退出登录时 [reset]。 */
class ForgetViewModel(private val api: MemoApiClient) : ViewModel() {
    var uiState by mutableStateOf(ForgetUiState())
        private set
    private var loadJob: Job? = null
    private var mutationJob: Job? = null
    private var previewJob: Job? = null
    private var previewItemId: String? = null

    fun reset() {
        loadJob?.cancel()
        mutationJob?.cancel()
        previewJob?.cancel()
        previewItemId = null
        uiState = ForgetUiState()
    }

    fun clearMessage() {
        uiState = uiState.copy(error = null, message = null)
    }

    fun showError(message: UiText) {
        uiState = uiState.copy(error = message, message = null)
    }

    fun load(query: String) {
        loadJob?.cancel()
        uiState = uiState.copy(query = query, loading = true)
        loadJob = viewModelScope.launch {
            try {
                val items = withContext(Dispatchers.IO) { api.listForgetItems(query) }
                if (uiState.query != query) return@launch
                uiState = uiState.copy(items = items, loading = false, error = null)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (uiState.query == query) {
                    uiState = uiState.copy(loading = false, error = describe(error))
                }
            }
        }
    }

    fun clearPreviews() {
        previewJob?.cancel()
        previewItemId = null
        uiState = uiState.copy(previews = emptyMap(), previewNotes = emptyMap())
    }

    fun refreshPreviews(item: ForgetItem) {
        previewJob?.cancel()
        previewItemId = item.id
        uiState = uiState.copy(previews = emptyMap(), previewNotes = emptyMap())
        val images = item.attachments.filter(::isForgetImage)
        if (images.isEmpty()) return
        previewJob = viewModelScope.launch {
            val notes = linkedMapOf<String, UiText>()
            val bytes = linkedMapOf<String, ByteArray>()
            for (attachment in images) {
                if (previewItemId != item.id) return@launch
                if (attachment.size > FORGET_PREVIEW_MAX_BYTES) {
                    notes[attachment.id] = UiText.res(R.string.forget_preview_too_large)
                    continue
                }
                try {
                    val data = withContext(Dispatchers.IO) {
                        val output = ByteArrayOutputStream()
                        api.downloadForgetAttachment(item.id, attachment.id, output)
                        output.toByteArray()
                    }
                    bytes[attachment.id] = data
                } catch (error: CancellationException) {
                    throw error
                } catch (_: Exception) {
                    notes[attachment.id] = UiText.res(R.string.forget_preview_failed)
                }
                if (previewItemId == item.id) {
                    uiState = uiState.copy(previews = bytes.toMap(), previewNotes = notes.toMap())
                }
            }
        }
    }

    fun save(
        existingId: String?,
        version: Int,
        title: String,
        content: String,
        pinned: Boolean,
        onSaved: (ForgetItem) -> Unit,
    ) {
        val problem = forgetTextError(title, content)
        if (problem != null) {
            showError(problem)
            return
        }
        val input = ForgetItemInput(title.trim(), content.trim(), pinned)
        val itemId = existingId
        val creating = itemId == null || version < 1
        runAction {
            try {
                val saved = withContext(Dispatchers.IO) {
                    if (creating) api.createForgetItem(input)
                    else api.updateForgetItem(itemId, input, version)
                }
                replace(saved)
                onSaved(saved)
                uiState = uiState.copy(message = if (creating) UiText.res(R.string.forget_msg_recorded) else UiText.res(R.string.ledger_msg_saved))
            } catch (error: ApiException) {
                if (error.statusCode == 409) {
                    syncAfterConflict()
                    return@runAction
                }
                throw error
            }
        }
    }

    fun deleteItem(id: String, expectedVersion: Int, onDone: () -> Unit) {
        runAction {
            try {
                withContext(Dispatchers.IO) { api.deleteForgetItem(id, expectedVersion) }
                if (previewItemId == id) clearPreviews()
                uiState = uiState.copy(items = uiState.items.filter { it.id != id })
                onDone()
                uiState = uiState.copy(message = UiText.res(R.string.forget_msg_deleted))
            } catch (error: ApiException) {
                if (error.statusCode == 409) {
                    syncAfterConflict()
                    return@runAction
                }
                throw error
            }
        }
    }

    fun deleteAttachment(itemId: String, attachmentId: String) {
        runAction {
            withContext(Dispatchers.IO) { api.deleteForgetAttachment(itemId, attachmentId) }
            val items = uiState.items.map { item ->
                if (item.id != itemId) item
                else item.copy(attachments = item.attachments.filter { it.id != attachmentId })
            }
            uiState = uiState.copy(
                items = items,
                previews = uiState.previews - attachmentId,
                previewNotes = uiState.previewNotes - attachmentId,
                message = UiText.res(R.string.forget_msg_attachment_deleted),
            )
        }
    }

    fun uploadFiles(
        existingId: String?,
        title: String,
        content: String,
        pinned: Boolean,
        uris: List<Uri>,
        contentResolver: ContentResolver,
        onItem: (ForgetItem) -> Unit,
    ) {
        if (uris.isEmpty() || uiState.busy) return
        if (existingId == null) {
            val problem = forgetTextError(title, content)
            if (problem != null) {
                showError(problem)
                return
            }
        }
        runAction {
            var item = resolveItem(existingId, title, content, pinned)
            onItem(item)
            for (uri in uris) {
                if (item.attachments.size >= FORGET_MAX_ATTACHMENTS) {
                    throw UiTextException(UiText.res(R.string.forget_error_too_many_attachments))
                }
                val (queriedName, size) = withContext(Dispatchers.IO) {
                    queryNameAndSize(contentResolver, uri)
                }
                val name = queriedName.ifBlank { "file" }
                forgetFileError(size)?.let { throw UiTextException(UiText.res(R.string.forget_error_named_file, name, it)) }
                val bytes = withContext(Dispatchers.IO) { readLimited(contentResolver, uri, name) }
                if (bytes.isEmpty()) throw UiTextException(UiText.res(R.string.forget_error_named_file, name, UiText.res(R.string.error_attachment_empty)))
                val mime = contentResolver.getType(uri)?.ifBlank { null }
                item = withContext(Dispatchers.IO) {
                    api.uploadForgetAttachment(item.id, bytes, name, mime)
                }
                replace(item)
                onItem(item)
            }
            refreshPreviews(item)
            uiState = uiState.copy(message = UiText.res(R.string.forget_msg_attachment_saved))
        }
    }

    /** 把附件写进用户选好的位置。失败时删掉空文件。下载不会删除服务器上的附件。 */
    fun saveAttachment(
        itemId: String,
        attachmentId: String,
        displayName: String,
        uri: Uri,
        contentResolver: ContentResolver,
    ) {
        runAction {
            try {
                withContext(Dispatchers.IO) {
                    val output = contentResolver.openOutputStream(uri, "w")
                        ?: throw java.io.IOException("Cannot write to the selected location")
                    output.use { api.downloadForgetAttachment(itemId, attachmentId, it) }
                }
            } catch (error: Exception) {
                withContext(Dispatchers.IO) {
                    runCatching { DocumentsContract.deleteDocument(contentResolver, uri) }
                }
                throw error
            }
            uiState = uiState.copy(message = UiText.res(R.string.forget_msg_file_saved, displayName))
        }
    }

    private suspend fun resolveItem(
        existingId: String?,
        title: String,
        content: String,
        pinned: Boolean,
    ): ForgetItem {
        if (existingId != null) {
            // 搜索结果里可能暂时没有这条，附件上限仍由服务端拒绝。
            return uiState.items.find { it.id == existingId }
                ?: ForgetItem(existingId, title.trim(), content.trim(), pinned, 1, "", "", emptyList())
        }
        val created = withContext(Dispatchers.IO) {
            api.createForgetItem(ForgetItemInput(title.trim(), content.trim(), pinned))
        }
        replace(created)
        return created
    }

    private suspend fun syncAfterConflict() {
        val items = withContext(Dispatchers.IO) { api.listForgetItems(uiState.query) }
        uiState = uiState.copy(
            items = items,
            textEpoch = uiState.textEpoch + 1,
            error = UiText.res(R.string.forget_conflict_reloading),
        )
    }

    private fun replace(item: ForgetItem) {
        val items = uiState.items.toMutableList()
        val index = items.indexOfFirst { it.id == item.id }
        if (index >= 0) items[index] = item else items.add(0, item)
        uiState = uiState.copy(items = items)
    }

    private fun runAction(block: suspend () -> Unit) {
        if (uiState.busy) return
        mutationJob?.cancel()
        mutationJob = viewModelScope.launch {
            uiState = uiState.copy(busy = true, error = null, message = null)
            try {
                block()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(error = describe(error))
            } finally {
                uiState = uiState.copy(busy = false)
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

    /** 大小未知时边读边数，超过 20 MB 立刻停止。 */
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
                if (total > FORGET_MAX_ATTACHMENT_BYTES) {
                    throw UiTextException(UiText.res(R.string.forget_error_named_file, name, UiText.res(R.string.forget_error_attachment_too_large)))
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
        is IllegalArgumentException -> error.message?.let(UiText::plain) ?: UiText.res(R.string.forget_error_cannot_save_file)
        is java.io.IOException -> UiText.res(R.string.forget_error_offline)
        is SecurityException -> UiText.res(R.string.relay_error_permission)
        else -> UiText.res(R.string.error_operation_failed_later)
    }

    companion object {
        fun factory(api: MemoApiClient): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = ForgetViewModel(api) as T
        }
    }
}
