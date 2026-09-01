package com.memoisle.app.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val DeepTeal = Color(0xFF177A72)
val DeepTealHover = Color(0xFF0F625C)
val TealSoft = Color(0xFFE2F2EE)
val WarmMist = Color(0xFFF6F7F2)
val SurfaceWhite = Color(0xFFFFFFFF)
val SurfaceSubtle = Color(0xFFEEF2EF)
val TextStrong = Color(0xFF1E2B29)
val TextMuted = Color(0xFF687673)
val Border = Color(0xFFDCE4E0)
val WarmAmberSoft = Color(0xFFFFF2DF)
val WarmAmberText = Color(0xFF9C5D17)

private val MemoIsleColors = lightColorScheme(
    primary = DeepTeal,
    onPrimary = Color.White,
    primaryContainer = TealSoft,
    onPrimaryContainer = DeepTealHover,
    secondary = Color(0xFFE69A45),
    onSecondary = TextStrong,
    secondaryContainer = TealSoft,
    onSecondaryContainer = DeepTealHover,
    background = WarmMist,
    onBackground = TextStrong,
    surface = SurfaceWhite,
    onSurface = TextStrong,
    surfaceVariant = SurfaceSubtle,
    onSurfaceVariant = TextMuted,
    outline = Border,
    outlineVariant = Border,
    error = Color(0xFFB84A4A),
)

@Composable
fun MemoIsleTheme(content: @Composable () -> Unit) {
    // MVP 固定使用 Stitch 设计的浅色主题，后续再加入完整深色令牌。
    MaterialTheme(
        colorScheme = MemoIsleColors,
        typography = Typography(),
        content = content,
    )
}
