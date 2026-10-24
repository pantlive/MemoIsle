package com.memoisle.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.Translate
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD

/** 一种内容类型的图标、名称和配色。 */
data class MemoKindStyle(
    val icon: ImageVector,
    val label: String,
    val accent: Color,
    val soft: Color,
)

fun memoKindStyle(type: String, isVoice: Boolean = false): MemoKindStyle = when (type) {
    TYPE_WORD -> MemoKindStyle(Icons.Outlined.Translate, "单词", WordAccent, WordSoft)
    TYPE_RESOURCE -> MemoKindStyle(Icons.Outlined.Language, "网页资料", ResourceAccent, ResourceSoft)
    TYPE_IMAGE -> MemoKindStyle(Icons.Outlined.Image, "图片", ImageAccent, ImageSoft)
    else -> if (isVoice) {
        MemoKindStyle(Icons.Outlined.Mic, "语音灵感", IdeaAccent, IdeaSoft)
    } else {
        MemoKindStyle(Icons.Outlined.Lightbulb, "灵感", IdeaAccent, IdeaSoft)
    }
}

/** 浅色底的圆角方块里放类型图标，列表和快捷入口共用。 */
@Composable
fun KindAvatar(
    style: MemoKindStyle,
    modifier: Modifier = Modifier,
    size: Dp = 40.dp,
    iconSize: Dp = 22.dp,
) {
    Box(
        modifier = modifier
            .size(size)
            .background(style.soft, RoundedCornerShape(size * 0.3f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(style.icon, contentDescription = null, tint = style.accent, modifier = Modifier.size(iconSize))
    }
}

/** 由站点名算出固定色相，同一站点每次显示同一种颜色；不加载站点图标，避免向第三方暴露访问记录。 */
fun siteAvatarColor(text: String): Color {
    var hash = 0
    for (char in text) hash = (hash * 31 + char.code) % 360
    return Color.hsl(hash.toFloat(), 0.45f, 0.42f)
}

/** 网页资料用站点首字母做头像，和 Web 端、快速访问一致。 */
@Composable
fun SiteAvatar(
    name: String,
    modifier: Modifier = Modifier,
    size: Dp = 40.dp,
) {
    Box(
        modifier = modifier
            .size(size)
            .background(siteAvatarColor(name), RoundedCornerShape(size * 0.3f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            name.trim().firstOrNull()?.uppercase() ?: "?",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = (size.value * 0.42f).sp,
        )
    }
}

/**
 * 页面顶栏：左侧可选返回按钮和标题，右侧放图标操作。
 * 顶栏固定不随列表滚动，状态栏留白由这里处理。
 */
@Composable
fun MemoTopBar(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    brand: Boolean = false,
    navigationIcon: (@Composable () -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(WarmMist)
            .statusBarsPadding()
            .padding(start = if (navigationIcon == null) 20.dp else 4.dp, end = 4.dp)
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        navigationIcon?.invoke()
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = if (brand) {
                    MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold, fontSize = 22.sp)
                } else {
                    MaterialTheme.typography.titleLarge
                },
                color = if (brand) DeepTealHover else TextStrong,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            subtitle?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = TextMuted, maxLines = 1)
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, content = actions)
    }
}

/** 统一样式的筛选标签：选中为浅青底深青字，未选为白底描边。 */
@Composable
fun MemoFilterChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leadingIcon: ImageVector? = null,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label, style = MaterialTheme.typography.labelLarge) },
        modifier = modifier,
        leadingIcon = leadingIcon?.let { icon ->
            { Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp)) }
        },
        shape = RoundedCornerShape(10.dp),
        colors = FilterChipDefaults.filterChipColors(
            containerColor = SurfaceWhite,
            labelColor = TextMuted,
            iconColor = TextMuted,
            selectedContainerColor = TealSoft,
            selectedLabelColor = DeepTealHover,
            selectedLeadingIconColor = DeepTealHover,
        ),
        border = FilterChipDefaults.filterChipBorder(
            enabled = true,
            selected = selected,
            borderColor = Border,
            selectedBorderColor = Color.Transparent,
        ),
    )
}

/** 分区标题：左侧标题，右侧灰色说明，例如数量。 */
@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    trailing: String? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
        trailing?.let {
            Text(it, style = MaterialTheme.typography.labelMedium, color = TextMuted)
        }
    }
}

/** 小号胶囊标签，用于分类、状态等元信息。 */
@Composable
fun InfoPill(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = TextMuted,
    background: Color = SurfaceSubtle,
    icon: ImageVector? = null,
) {
    Row(
        modifier = modifier
            .background(background, RoundedCornerShape(999.dp))
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        icon?.let {
            Icon(it, contentDescription = null, tint = color, modifier = Modifier.size(14.dp))
            Spacer(Modifier.width(4.dp))
        }
        Text(text, color = color, style = MaterialTheme.typography.labelMedium, maxLines = 1)
    }
}

/**
 * 全屏详情页：顶部关闭按钮、类型和操作，中间可滚动内容，底部固定主操作。
 * 取代原来挤在 AlertDialog 里的详情，内容多时不再被压缩。
 */
@Composable
fun DetailScreen(
    kind: MemoKindStyle,
    onClose: () -> Unit,
    actions: @Composable RowScope.() -> Unit = {},
    bottomBar: (@Composable RowScope.() -> Unit)? = null,
    closeEnabled: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    Dialog(
        onDismissRequest = { if (closeEnabled) onClose() },
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Surface(modifier = Modifier.fillMaxSize(), color = SurfaceWhite) {
            Column(Modifier.fillMaxSize().imePadding()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .padding(horizontal = 4.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = onClose, enabled = closeEnabled) {
                        Icon(Icons.Outlined.Close, contentDescription = "关闭")
                    }
                    Row(
                        modifier = Modifier.weight(1f),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(kind.icon, contentDescription = null, tint = kind.accent, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(kind.label, color = kind.accent, style = MaterialTheme.typography.labelLarge)
                    }
                    actions()
                }
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 20.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                    content = content,
                )
                if (bottomBar != null) {
                    HorizontalDivider(color = Border)
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .navigationBarsPadding()
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End),
                        verticalAlignment = Alignment.CenterVertically,
                        content = bottomBar,
                    )
                } else {
                    Spacer(Modifier.navigationBarsPadding())
                }
            }
        }
    }
}

/** 详情页里的小标题加内容块。 */
@Composable
fun DetailField(
    label: String,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label, color = TextMuted, style = MaterialTheme.typography.labelMedium)
        content()
    }
}

val CardPadding = PaddingValues(horizontal = 16.dp, vertical = 14.dp)
