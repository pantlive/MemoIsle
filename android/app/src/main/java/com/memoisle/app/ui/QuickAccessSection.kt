package com.memoisle.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.memoisle.app.data.Memo
import com.memoisle.app.network.QuickAccessEntry

// 首页「快速访问」网页资料区块。（从 MemoHomeScreen.kt 拆出）

private fun quickAccessHost(url: String?): String {
    return url?.let { runCatching { java.net.URI(it).host?.removePrefix("www.") }.getOrNull() }.orEmpty()
}

@Composable
internal fun QuickAccessSection(
    entries: List<QuickAccessEntry>,
    onOpen: (Memo) -> Unit,
    onRemove: (Memo) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionHeader("快速访问", trailing = "按打开次数排列")
        if (entries.isEmpty()) {
            Text(
                "还没有打开记录。点开网页资料的「打开原网页」后，常用的网页会按打开次数出现在这里。",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
            return@Column
        }
        // 横向滑动、宽度一致的卡片，不再像换行排列那样长短不齐。
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(end = 4.dp),
        ) {
            items(entries, key = { it.memo.clientId }) { entry ->
                val memo = entry.memo
                val host = quickAccessHost(memo.sourceUrl)
                val summary = resourceSummary(memo)
                Card(
                    onClick = { onOpen(memo) },
                    modifier = Modifier.width(176.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
                    border = BorderStroke(1.dp, Border),
                ) {
                    Column(Modifier.padding(start = 12.dp, top = 12.dp, bottom = 12.dp, end = 4.dp)) {
                        Row(verticalAlignment = Alignment.Top) {
                            SiteAvatar(host.ifBlank { memo.title }, size = 34.dp)
                            Spacer(Modifier.weight(1f))
                            IconButton(
                                onClick = { onRemove(memo) },
                                modifier = Modifier.size(28.dp),
                            ) {
                                Icon(
                                    Icons.Outlined.Close,
                                    contentDescription = "从快速访问移除「${memo.title}」",
                                    tint = TextMuted,
                                    modifier = Modifier.size(16.dp),
                                )
                            }
                        }
                        Spacer(Modifier.height(10.dp))
                        Text(
                            memo.title,
                            style = MaterialTheme.typography.titleSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                        // 固定两行高度，有无简介的卡片都一样高。
                        Text(
                            summary ?: "暂无简介",
                            color = if (summary == null) TextMuted.copy(alpha = 0.6f) else TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                            minLines = 2,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 2.dp, end = 8.dp),
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "${entry.openCount} 次 · $host",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                    }
                }
            }
        }
    }
}
