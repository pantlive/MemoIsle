package com.memoisle.app.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.memoisle.app.ForgetViewModel
import com.memoisle.app.R
import com.memoisle.app.data.ForgetAttachment
import com.memoisle.app.data.ForgetItem
import com.memoisle.app.data.forgetDisplayTitle
import com.memoisle.app.data.forgetSaveName
import com.memoisle.app.data.forgetSaveType
import com.memoisle.app.data.forgetTextLength
import com.memoisle.app.data.formatForgetBytes
import com.memoisle.app.data.isForgetImage
import kotlinx.coroutines.delay

/** 系统「另存为」。文件名和类型按附件设置，非图片用二进制类型。 */
private class CreateForgetDocument : ActivityResultContract<Pair<String, String>, Uri?>() {
    override fun createIntent(context: Context, input: Pair<String, String>): Intent =
        Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(input.second.ifBlank { "application/octet-stream" })
            .putExtra(Intent.EXTRA_TITLE, input.first)

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        if (resultCode == Activity.RESULT_OK) intent?.data else null
}

/**
 * 在线易忘事项：文字、多张图片和多个文件。不缓存到本地数据库。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ForgetScreen(viewModel: ForgetViewModel, onClose: () -> Unit) {
    val state = viewModel.uiState
    val context = LocalContext.current
    var query by rememberSaveable { mutableStateOf("") }
    var editingId by rememberSaveable { mutableStateOf<String?>(null) }
    var version by rememberSaveable { mutableIntStateOf(0) }
    var title by rememberSaveable { mutableStateOf("") }
    var content by rememberSaveable { mutableStateOf("") }
    var pinned by rememberSaveable { mutableStateOf(false) }
    var pendingDelete by rememberSaveable { mutableStateOf(false) }
    var pendingAttachmentId by rememberSaveable { mutableStateOf<String?>(null) }
    var pendingSaveId by remember { mutableStateOf<String?>(null) }

    val selected = state.items.find { it.id == editingId }
    val attachments = selected?.attachments.orEmpty()
    val pendingAttachment = attachments.find { it.id == pendingAttachmentId }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        viewModel.uploadFiles(editingId, title, content, pinned, uris, context.contentResolver) { saved ->
            editingId = saved.id
            version = saved.version
        }
    }
    val saveLauncher = rememberLauncherForActivityResult(CreateForgetDocument()) { uri ->
        val attachment = attachments.find { it.id == pendingSaveId }
        val itemId = editingId
        pendingSaveId = null
        if (uri == null || attachment == null || itemId == null) return@rememberLauncherForActivityResult
        viewModel.saveAttachment(itemId, attachment.id, attachment.originalName, uri, context.contentResolver)
    }

    LaunchedEffect(query) {
        delay(300)
        viewModel.load(query)
    }
    LaunchedEffect(state.textEpoch) {
        if (state.textEpoch == 0) return@LaunchedEffect
        val current = state.items.find { it.id == editingId } ?: return@LaunchedEffect
        version = current.version
        title = current.title
        content = current.content
        pinned = current.pinned
        viewModel.refreshPreviews(current)
    }
    BackHandler(onBack = onClose)

    fun select(item: ForgetItem) {
        pendingDelete = false
        pendingAttachmentId = null
        editingId = item.id
        version = item.version
        title = item.title
        content = item.content
        pinned = item.pinned
        viewModel.refreshPreviews(item)
    }

    fun startNew() {
        pendingDelete = false
        pendingAttachmentId = null
        editingId = null
        version = 0
        title = ""
        content = ""
        pinned = false
        viewModel.clearPreviews()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.forget_title)) },
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = stringResource(R.string.common_back))
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text(
                    stringResource(R.string.forget_intro),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (state.message != null) {
                item { Text(state.message.asString(), color = MaterialTheme.colorScheme.primary) }
            }
            if (state.error != null) {
                item { Text(state.error.asString(), color = MaterialTheme.colorScheme.error) }
            }
            item {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.forget_search)) },
                    singleLine = true,
                )
            }
            item {
                Button(onClick = ::startNew, enabled = !state.busy) { Text(stringResource(R.string.forget_new)) }
            }
            if (state.loading && state.items.isEmpty()) {
                item { CircularProgressIndicator() }
            } else if (state.items.isEmpty()) {
                item { Text(stringResource(R.string.forget_empty)) }
            } else {
                items(state.items, key = { it.id }) { item ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        onClick = { select(item) },
                    ) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(
                                if (item.pinned) {
                                    stringResource(R.string.forget_pinned_title, forgetDisplayTitle(item.title))
                                } else {
                                    forgetDisplayTitle(item.title)
                                },
                                style = MaterialTheme.typography.titleMedium,
                            )
                            val attachmentsLabel = if (item.attachments.isEmpty()) {
                                stringResource(R.string.forget_no_attachments)
                            } else {
                                pluralStringResource(R.plurals.forget_attachment_count, item.attachments.size, item.attachments.size)
                            }
                            Text(
                                buildString {
                                    append(attachmentsLabel)
                                    if (item.content.isNotBlank()) append(" · ${item.content.trim().take(40)}")
                                },
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
            item {
                Text(if (editingId == null) stringResource(R.string.forget_new_item) else stringResource(R.string.common_edit), style = MaterialTheme.typography.titleMedium)
            }
            item {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.forget_title_counter, forgetTextLength(title.trim()))) },
                    singleLine = true,
                )
            }
            item {
                OutlinedTextField(
                    value = content,
                    onValueChange = { content = it },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 120.dp),
                    label = { Text(stringResource(R.string.forget_content_counter, forgetTextLength(content.trim()))) },
                )
            }
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = pinned, onCheckedChange = { pinned = it })
                    Text(stringResource(R.string.forget_pin))
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = {
                            viewModel.save(editingId, version, title, content, pinned) { saved ->
                                editingId = saved.id
                                version = saved.version
                                title = saved.title
                                content = saved.content
                                pinned = saved.pinned
                            }
                        },
                        enabled = !state.busy,
                    ) { Text(if (editingId == null) stringResource(R.string.forget_record) else stringResource(R.string.forget_save_text)) }
                    if (editingId != null) {
                        OutlinedButton(onClick = { pendingDelete = true }, enabled = !state.busy) {
                            Text(stringResource(R.string.forget_delete_item))
                        }
                    }
                }
            }
            item {
                OutlinedButton(
                    onClick = { filePicker.launch(arrayOf("*/*")) },
                    enabled = !state.busy,
                ) { Text(stringResource(R.string.forget_choose_files)) }
                Text(
                    stringResource(R.string.forget_files_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            items(attachments, key = { it.id }) { attachment ->
                AttachmentRow(
                    attachment = attachment,
                    preview = state.previews[attachment.id],
                    note = state.previewNotes[attachment.id]?.asString(),
                    enabled = !state.busy,
                    onSave = {
                        pendingSaveId = attachment.id
                        val launched = runCatching {
                            saveLauncher.launch(forgetSaveName(attachment.originalName) to forgetSaveType(attachment))
                        }
                        if (launched.isFailure) {
                            pendingSaveId = null
                            viewModel.showError(UiText.res(R.string.relay_ui_no_file_manager))
                        }
                    },
                    onDelete = { pendingAttachmentId = attachment.id },
                )
            }
            item { Text("") }
        }
    }

    if (pendingDelete && editingId != null) {
        AlertDialog(
            onDismissRequest = { if (!state.busy) pendingDelete = false },
            title = { Text(stringResource(R.string.forget_delete_title)) },
            text = { Text(stringResource(R.string.forget_delete_text)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        val id = editingId ?: return@TextButton
                        viewModel.deleteItem(id, version) {
                            pendingDelete = false
                            startNew()
                        }
                    },
                    enabled = !state.busy,
                ) { Text(stringResource(R.string.forget_confirm_delete)) }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = false }, enabled = !state.busy) { Text(stringResource(R.string.common_cancel)) }
            },
        )
    }
    if (pendingAttachment != null && editingId != null) {
        AlertDialog(
            onDismissRequest = { if (!state.busy) pendingAttachmentId = null },
            title = { Text(stringResource(R.string.forget_delete_attachment_title)) },
            text = { Text(stringResource(R.string.forget_delete_attachment_text, pendingAttachment.originalName)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        val id = editingId ?: return@TextButton
                        viewModel.deleteAttachment(id, pendingAttachment.id)
                        pendingAttachmentId = null
                    },
                    enabled = !state.busy,
                ) { Text(stringResource(R.string.forget_confirm_delete)) }
            },
            dismissButton = {
                TextButton(onClick = { pendingAttachmentId = null }, enabled = !state.busy) { Text(stringResource(R.string.common_cancel)) }
            },
        )
    }
}

@Composable
private fun AttachmentRow(
    attachment: ForgetAttachment,
    preview: ByteArray?,
    note: String?,
    enabled: Boolean,
    onSave: () -> Unit,
    onDelete: () -> Unit,
) {
    val image = remember(preview) { preview?.let(::decodeForgetPreview) }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (image != null) {
                Image(
                    bitmap = image,
                    contentDescription = attachment.originalName,
                    modifier = Modifier.size(96.dp),
                    contentScale = ContentScale.Crop,
                )
            }
            Text(attachment.originalName.ifBlank { "file" })
            Text(
                stringResource(
                    R.string.forget_attachment_meta,
                    stringResource(if (isForgetImage(attachment)) R.string.kind_image else R.string.forget_kind_file),
                    formatForgetBytes(attachment.size),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (note != null) Text(note, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onSave, enabled = enabled) { Text(stringResource(R.string.forget_save_as)) }
                OutlinedButton(onClick = onDelete, enabled = enabled) { Text(stringResource(R.string.common_delete)) }
            }
        }
    }
}

private fun decodeForgetPreview(bytes: ByteArray): ImageBitmap? = runCatching {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return@runCatching null
    var sample = 1
    while (bounds.outWidth / sample > 720 || bounds.outHeight / sample > 720) sample *= 2
    val options = BitmapFactory.Options().apply { inSampleSize = sample }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.asImageBitmap()
}.getOrNull()
