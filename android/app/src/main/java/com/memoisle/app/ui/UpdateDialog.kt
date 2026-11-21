package com.memoisle.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import com.memoisle.app.R
import com.memoisle.app.UpdatePhase
import com.memoisle.app.UpdateUiState
import com.memoisle.app.data.formatRelayBytes

/**
 * 新版本提示：版本号、更新说明、下载进度。
 * 按钮为「更新 / 稍后 / 忽略此版本」，下载完成后变为「安装」。
 */
@Composable
fun UpdateDialog(
    state: UpdateUiState,
    currentVersionName: String,
    onUpdate: () -> Unit,
    onInstall: () -> Unit,
    onLater: () -> Unit,
    onIgnore: () -> Unit,
) {
    val release = state.release ?: return
    val downloading = state.phase == UpdatePhase.DOWNLOADING
    AlertDialog(
        // 下载中点外面不关闭，避免误触取消；要取消请点「稍后」。
        onDismissRequest = { if (!downloading) onLater() },
        properties = DialogProperties(dismissOnClickOutside = !downloading),
        containerColor = SurfaceWhite,
        title = { Text(stringResource(R.string.update_dialog_title, release.versionName), fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    stringResource(R.string.update_dialog_current, currentVersionName, formatRelayBytes(release.size)),
                    style = MaterialTheme.typography.bodySmall,
                    color = TextMuted,
                )
                if (release.releaseNotes.isNotBlank()) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 220.dp)
                            .verticalScroll(rememberScrollState()),
                    ) {
                        Text(release.releaseNotes, style = MaterialTheme.typography.bodyMedium, color = TextStrong)
                    }
                }
                when (state.phase) {
                    UpdatePhase.DOWNLOADING -> {
                        val progress = state.progress
                        if (progress == null) {
                            LinearProgressIndicator(modifier = Modifier.fillMaxWidth(), color = DeepTeal)
                        } else {
                            LinearProgressIndicator(
                                progress = { progress },
                                modifier = Modifier.fillMaxWidth(),
                                color = DeepTeal,
                            )
                        }
                        Text(
                            if (progress == null) stringResource(R.string.update_downloading) else stringResource(R.string.update_downloading_progress, (progress * 100).toInt()),
                            style = MaterialTheme.typography.bodySmall,
                            color = TextMuted,
                        )
                    }
                    UpdatePhase.DOWNLOADED -> Text(
                        stringResource(R.string.update_downloaded_hint),
                        style = MaterialTheme.typography.bodySmall,
                        color = TextMuted,
                    )
                    UpdatePhase.FAILED -> Text(
                        state.message?.asString() ?: stringResource(R.string.update_failed),
                        style = MaterialTheme.typography.bodySmall,
                        color = DangerRed,
                    )
                    else -> Unit
                }
            }
        },
        confirmButton = {
            when (state.phase) {
                UpdatePhase.DOWNLOADED -> Button(onClick = onInstall) { Text(stringResource(R.string.update_install)) }
                UpdatePhase.FAILED -> Button(onClick = onUpdate) { Text(stringResource(R.string.update_retry)) }
                else -> Button(onClick = onUpdate, enabled = !downloading) {
                    Text(if (downloading) stringResource(R.string.update_downloading) else stringResource(R.string.update_update))
                }
            }
        },
        dismissButton = {
            Row {
                if (state.phase == UpdatePhase.AVAILABLE) {
                    TextButton(onClick = onIgnore) { Text(stringResource(R.string.update_ignore_version), color = TextMuted) }
                }
                TextButton(onClick = onLater) { Text(if (downloading) stringResource(R.string.common_cancel) else stringResource(R.string.update_later)) }
            }
        },
    )
}
