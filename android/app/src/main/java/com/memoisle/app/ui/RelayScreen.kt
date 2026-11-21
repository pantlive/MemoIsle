package com.memoisle.app.ui

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.memoisle.app.R
import com.memoisle.app.RelayViewModel
import com.memoisle.app.data.RelayItem
import com.memoisle.app.data.formatRelayBytes
import com.memoisle.app.data.formatRelayRemaining
import com.memoisle.app.data.relayClipboardImageName
import com.memoisle.app.data.relayDeviceLabel
import com.memoisle.app.update.AppUpdater
import java.io.File
import kotlinx.coroutines.delay

/** 系统「另存为」，文件名和类型按收到的内容逐条设置。 */
private class CreateRelayDocument : ActivityResultContract<Pair<String, String>, Uri?>() {
    override fun createIntent(context: Context, input: Pair<String, String>): Intent =
        Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(input.second)
            .putExtra(Intent.EXTRA_TITLE, input.first)

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        if (resultCode == Activity.RESULT_OK) intent?.data else null
}

/**
 * 手机与网页互传文字、图片、小文件。服务端只在内存里转发，取走即删，10 分钟内有效。
 * 页面可见时自动接收，App 退到后台时暂停。
 */
@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun RelayScreen(viewModel: RelayViewModel, onClose: () -> Unit) {
    val state = viewModel.uiState
    val context = LocalContext.current
    val resources = LocalResources.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val snackbarHostState = remember { SnackbarHostState() }
    var text by rememberSaveable { mutableStateOf("") }
    var pendingSave by remember { mutableStateOf<RelayItem?>(null) }
    var pendingLocalFile by remember { mutableStateOf<File?>(null) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) viewModel.sendFile(uri, context.contentResolver)
    }
    val saveLauncher = rememberLauncherForActivityResult(CreateRelayDocument()) { uri ->
        val item = pendingSave
        val local = pendingLocalFile
        pendingSave = null
        pendingLocalFile = null
        if (uri == null) {
            if (local != null) {
                viewModel.showError(UiText.res(R.string.relay_ui_clipboard_failed_no_location))
            }
            return@rememberLauncherForActivityResult
        }
        if (local != null) {
            viewModel.saveCachedFile(local, uri, context.contentResolver, item?.filename ?: local.name)
        } else if (item != null) {
            viewModel.saveFile(item, uri, context.contentResolver)
        }
    }

    fun pasteClipboardImage() {
        val clipboard = context.getSystemService(ClipboardManager::class.java)
        if (clipboard == null) {
            viewModel.showError(UiText.res(R.string.relay_ui_no_clipboard_image))
            return
        }
        try {
            val clip = clipboard.primaryClip
            val description = clip?.description
            if (clip == null || description == null) {
                viewModel.showError(UiText.res(R.string.relay_ui_no_clipboard_image))
                return
            }
            for (index in 0 until clip.itemCount) {
                val uri = clip.getItemAt(index).uri ?: continue
                val mime = context.contentResolver.getType(uri)
                    ?: (0 until description.mimeTypeCount)
                        .map { description.getMimeType(it) }
                        .firstOrNull { it.startsWith("image/", ignoreCase = true) }
                val looksLikeImage = description.hasMimeType("image/*") ||
                    mime?.startsWith("image/") == true
                if (!looksLikeImage) continue
                viewModel.sendFile(
                    uri,
                    context.contentResolver,
                    relayClipboardImageName(mime, System.currentTimeMillis()),
                )
                return
            }
            viewModel.showError(UiText.res(R.string.relay_ui_no_clipboard_image))
        } catch (_: SecurityException) {
            viewModel.showError(UiText.res(R.string.relay_error_permission))
        }
    }

    fun copyReceivedImage(item: RelayItem) {
        viewModel.copyImage(item, context.cacheDir) { file ->
            val copied = runCatching {
                val uri = FileProvider.getUriForFile(
                    context,
                    "${context.packageName}${AppUpdater.AUTHORITY_SUFFIX}",
                    file,
                )
                val clipboard = context.getSystemService(ClipboardManager::class.java)
                    ?: error("Clipboard is unavailable")
                clipboard.setPrimaryClip(ClipData.newUri(context.contentResolver, resources.getString(R.string.relay_ui_clip_label_image), uri))
            }.isSuccess
            if (!copied) {
                pendingLocalFile = file
                pendingSave = item
                viewModel.showError(UiText.res(R.string.relay_ui_clipboard_failed_choose))
                runCatching {
                    saveLauncher.launch(
                        (item.filename ?: file.name) to (item.mimeType ?: "image/*"),
                    )
                }.onFailure {
                    pendingLocalFile = null
                    pendingSave = null
                    viewModel.showError(UiText.res(R.string.relay_ui_clipboard_failed_no_manager))
                }
            }
        }
    }

    BackHandler(onBack = onClose)
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> viewModel.startPolling()
                Lifecycle.Event.ON_STOP -> viewModel.stopPolling()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            viewModel.stopPolling()
        }
    }
    LaunchedEffect(state.message, state.error) {
        val message = state.error ?: state.message ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message.resolve(resources))
        viewModel.clearMessage()
    }
    // 有待接收内容时每秒刷新倒计时。
    LaunchedEffect(state.items.isNotEmpty()) {
        while (state.items.isNotEmpty()) {
            now = System.currentTimeMillis()
            delay(1_000)
        }
    }

    fun copy(value: String) {
        val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return
        clipboard.setPrimaryClip(ClipData.newPlainText("MemoIsle", value))
    }

    val busy = state.sending || state.busyId != null
    val visible = state.items.filter { (state.deadlines[it.id] ?: 0L) > now }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text(stringResource(R.string.relay_ui_title)) }, navigationIcon = {
                IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, stringResource(R.string.common_back)) }
            })
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text(
                    stringResource(R.string.relay_ui_intro),
                    style = MaterialTheme.typography.bodySmall,
                    color = TextMuted,
                )
            }
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(stringResource(R.string.relay_ui_send_to_web), style = MaterialTheme.typography.titleMedium)
                        OutlinedTextField(
                            value = text,
                            onValueChange = { text = it },
                            label = { Text(stringResource(R.string.relay_ui_text_label)) },
                            placeholder = { Text(stringResource(R.string.relay_ui_text_placeholder)) },
                            enabled = !state.sending,
                            modifier = Modifier.fillMaxWidth().heightIn(min = 96.dp),
                            maxLines = 8,
                        )
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Button(
                                enabled = !busy && text.isNotBlank(),
                                onClick = { viewModel.sendText(text) { text = "" } },
                            ) { Text(if (state.sending) stringResource(R.string.relay_ui_sending) else stringResource(R.string.relay_ui_send_text)) }
                            Button(
                                enabled = !busy,
                                onClick = { pasteClipboardImage() },
                            ) { Text(stringResource(R.string.relay_ui_paste_image)) }
                            OutlinedButton(
                                enabled = !busy,
                                onClick = { filePicker.launch(arrayOf("*/*")) },
                            ) { Text(stringResource(R.string.relay_ui_choose_file)) }
                        }
                        Text(stringResource(R.string.relay_ui_file_limit), style = MaterialTheme.typography.bodySmall, color = TextMuted)
                    }
                }
            }
            item {
                Text(stringResource(R.string.relay_ui_received), style = MaterialTheme.typography.titleMedium)
                Text(
                    state.pollError?.asString() ?: stringResource(R.string.relay_ui_keep_open),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (state.pollError != null) MaterialTheme.colorScheme.error else TextMuted,
                )
            }
            if (visible.isEmpty()) {
                item {
                    Text(
                        stringResource(R.string.relay_ui_empty),
                        modifier = Modifier.padding(vertical = 24.dp),
                        color = TextMuted,
                    )
                }
            }
            items(visible, key = { it.id }) { item ->
                val remaining = ((state.deadlines[item.id] ?: now) - now) / 1_000
                val itemBusy = state.busyId == item.id
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            stringResource(
                                R.string.relay_item_meta,
                                relayDeviceLabel(item.source).asString(),
                                formatRelayBytes(item.size),
                                formatRelayRemaining(remaining).asString(),
                            ),
                            style = MaterialTheme.typography.bodySmall,
                            color = TextMuted,
                        )
                        if (item.isText) {
                            SelectionContainer { Text(item.text.orEmpty(), maxLines = 12) }
                        } else {
                            Text(item.filename ?: "file", style = MaterialTheme.typography.titleSmall)
                        }
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            if (item.isText) {
                                Button(enabled = !busy, onClick = { viewModel.copyText(item, ::copy) }) {
                                    Text(stringResource(R.string.common_copy))
                                }
                            } else if (item.isImage) {
                                Button(enabled = !busy, onClick = { copyReceivedImage(item) }) {
                                    Text(if (itemBusy) stringResource(R.string.relay_ui_copying) else stringResource(R.string.relay_ui_copy_image))
                                }
                                OutlinedButton(enabled = !busy, onClick = {
                                    pendingLocalFile = null
                                    pendingSave = item
                                    runCatching {
                                        saveLauncher.launch(
                                            (item.filename ?: "file") to
                                                (item.mimeType ?: "image/*"),
                                        )
                                    }.onFailure {
                                        pendingSave = null
                                        viewModel.showError(UiText.res(R.string.relay_ui_no_file_manager))
                                    }
                                }) { Text(if (itemBusy) stringResource(R.string.relay_ui_saving) else stringResource(R.string.common_save)) }
                            } else {
                                Button(enabled = !busy, onClick = {
                                    pendingLocalFile = null
                                    pendingSave = item
                                    runCatching {
                                        saveLauncher.launch(
                                            (item.filename ?: "file") to
                                                (item.mimeType ?: "application/octet-stream"),
                                        )
                                    }.onFailure {
                                        pendingSave = null
                                        viewModel.showError(UiText.res(R.string.relay_ui_no_file_manager))
                                    }
                                }) { Text(if (itemBusy) stringResource(R.string.relay_ui_saving) else stringResource(R.string.common_save)) }
                            }
                            TextButton(enabled = !busy, onClick = { viewModel.discard(item) }) { Text(stringResource(R.string.relay_ui_dismiss)) }
                        }
                    }
                }
            }
        }
    }
}
