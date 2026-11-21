package com.memoisle.app.ui

import android.content.res.Resources
import androidx.annotation.PluralsRes
import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.platform.LocalResources
import com.memoisle.app.R
import com.memoisle.app.network.ApiException

/**
 * 界面文案：ViewModel 和数据层只给出资源 id 和参数，到界面再按当前语言解析。
 * 这样切换语言（Activity 重建）后，ViewModel 里还没消费的提示也会用新语言显示。
 *
 * 参数可以是另一个 [UiText]，解析时先递归解析成文字；用户内容、服务端返回的
 * 说明等不需要翻译的文字用 [Plain] 原样显示。
 */
sealed interface UiText {
    data class Res(@param:StringRes val id: Int, val args: List<Any?> = emptyList()) : UiText

    data class Plural(@param:PluralsRes val id: Int, val count: Int, val args: List<Any?> = listOf(count)) : UiText

    data class Plain(val value: String) : UiText

    companion object {
        fun res(@StringRes id: Int, vararg args: Any?): UiText = Res(id, args.toList())

        /** 带数量的文案；不传 args 时把数量作为唯一参数。 */
        fun plural(@PluralsRes id: Int, count: Int, vararg args: Any?): UiText =
            Plural(id, count, if (args.isEmpty()) listOf(count) else args.toList())

        fun plain(value: String): UiText = Plain(value)
    }
}

fun UiText.resolve(resources: Resources): String = when (this) {
    is UiText.Plain -> value
    is UiText.Res -> if (args.isEmpty()) {
        resources.getString(id)
    } else {
        resources.getString(id, *resolveArgs(args, resources))
    }
    is UiText.Plural -> resources.getQuantityString(id, count, *resolveArgs(args, resources))
}

private fun resolveArgs(args: List<Any?>, resources: Resources): Array<Any?> =
    args.map { arg -> if (arg is UiText) arg.resolve(resources) else arg ?: "" }.toTypedArray()

/** 在 Compose 里按当前语言解析；语言切换引起配置变化时会重新组合。 */
@Composable
@ReadOnlyComposable
fun UiText.asString(): String = resolve(LocalResources.current)

@Composable
@ReadOnlyComposable
fun UiText?.asStringOrNull(): String? = this?.asString()

/** 自带界面文案的异常，[toUiText] 会直接用 [text]。 */
interface HasUiText {
    val text: UiText
}

/**
 * 带界面文案的异常：数据层校验失败时抛出，ViewModel 原样转给界面显示。
 * 继承 IllegalArgumentException，保持原来 `require(...)` 抛出的异常类型不变。
 */
open class UiTextException(override val text: UiText, cause: Throwable? = null) :
    IllegalArgumentException(text.toString(), cause), HasUiText

/** 与 [UiTextException] 相同，但保持原来 `IllegalStateException` 的类型。 */
open class UiTextStateException(override val text: UiText, cause: Throwable? = null) :
    IllegalStateException(text.toString(), cause), HasUiText

/** 抛出带界面文案的参数校验异常，替代 `require(condition) { "文案" }`。 */
inline fun requireUi(condition: Boolean, text: () -> UiText) {
    if (!condition) throw UiTextException(text())
}

/**
 * 把异常转成可显示的文案：带文案的异常直接用；服务端错误优先显示服务端的说明；
 * 其余异常显示其 message（截断），没有 message 时显示「未知错误」。
 */
fun Throwable.toUiText(maxLength: Int = 120): UiText = when (this) {
    is HasUiText -> text
    is ApiException -> UiText.res(
        R.string.error_api_request_failed,
        statusCode,
        (detailMessage ?: responseBody).take(maxLength),
    )
    else -> message?.take(maxLength)?.let(UiText::Plain) ?: UiText.res(R.string.error_unknown)
}

/** 同 [toUiText]，但普通异常没有 message 时显示 [fallback]。 */
fun Throwable.toUiText(@StringRes fallback: Int, maxLength: Int = 120): UiText =
    if (this !is HasUiText && this !is ApiException && message.isNullOrBlank()) {
        UiText.res(fallback)
    } else {
        toUiText(maxLength)
    }
