package com.memoisle.app.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

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
val DangerRed = Color(0xFFB84A4A)
val DangerSoft = Color(0xFFF8E7E7)

// 四类内容各有一个强调色，列表、快捷入口和详情里用同一套，扫一眼就能分出类型。
val IdeaAccent = WarmAmberText
val IdeaSoft = WarmAmberSoft
val WordAccent = Color(0xFF4A55A2)
val WordSoft = Color(0xFFECEEF8)
val ResourceAccent = DeepTeal
val ResourceSoft = TealSoft
val ImageAccent = Color(0xFFA8476A)
val ImageSoft = Color(0xFFFAEAF0)

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
    surfaceContainerLowest = SurfaceWhite,
    surfaceContainerLow = Color(0xFFFAFBF8),
    surfaceContainer = SurfaceWhite,
    surfaceContainerHigh = SurfaceWhite,
    surfaceContainerHighest = SurfaceSubtle,
    outline = Border,
    outlineVariant = Border,
    error = DangerRed,
)

// 中文为主的界面行高放宽一些，标题统一用 SemiBold。
private val MemoIsleTypography = Typography(
    headlineSmall = TextStyle(fontSize = 24.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold),
    titleLarge = TextStyle(fontSize = 20.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, lineHeight = 24.sp, fontWeight = FontWeight.SemiBold),
    titleSmall = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 25.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 22.sp),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
    labelLarge = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium),
    labelMedium = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium),
    labelSmall = TextStyle(fontSize = 11.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium),
)

private val MemoIsleShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(18.dp),
    extraLarge = RoundedCornerShape(24.dp),
)

@Composable
fun MemoIsleTheme(content: @Composable () -> Unit) {
    // MVP 固定使用 Stitch 设计的浅色主题，后续再加入完整深色令牌。
    MaterialTheme(
        colorScheme = MemoIsleColors,
        typography = MemoIsleTypography,
        shapes = MemoIsleShapes,
        content = content,
    )
}
