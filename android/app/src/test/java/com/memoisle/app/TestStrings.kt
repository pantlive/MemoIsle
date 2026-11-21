package com.memoisle.app

import com.memoisle.app.ui.UiText
import java.io.File
import java.util.Locale
import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Element

/**
 * JVM 单元测试里没有 Android Resources：直接解析 res/values 与 res/values-zh 下的 strings.xml，
 * 按 R 里的资源 id 找到名字，再把 [UiText] 解析成文字，便于断言中英文文案。
 */
object TestStrings {
    const val DEFAULT = "values"
    const val CHINESE = "values-zh"

    private val resDirectory: File by lazy {
        // Gradle 单元测试的工作目录是 app 模块；在仓库根目录运行时也能找到。
        listOf(File("src/main/res"), File("app/src/main/res"), File("android/app/src/main/res"))
            .firstOrNull { it.isDirectory }
            ?: error("找不到 res 目录：${File(".").absolutePath}")
    }

    private val stringNames: Map<Int, String> by lazy { resourceNames(R.string::class.java) }
    private val pluralNames: Map<Int, String> by lazy { resourceNames(R.plurals::class.java) }
    private val cache = mutableMapOf<String, Catalog>()

    data class Catalog(
        val strings: Map<String, String>,
        val plurals: Map<String, Map<String, String>>,
    )

    fun catalog(qualifier: String): Catalog = cache.getOrPut(qualifier) {
        val file = File(resDirectory, "$qualifier/strings.xml")
        val document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file)
        val strings = linkedMapOf<String, String>()
        val stringNodes = document.getElementsByTagName("string")
        for (index in 0 until stringNodes.length) {
            val element = stringNodes.item(index) as Element
            strings[element.getAttribute("name")] = unescape(element.textContent)
        }
        val plurals = linkedMapOf<String, Map<String, String>>()
        val pluralNodes = document.getElementsByTagName("plurals")
        for (index in 0 until pluralNodes.length) {
            val element = pluralNodes.item(index) as Element
            val items = linkedMapOf<String, String>()
            val itemNodes = element.getElementsByTagName("item")
            for (itemIndex in 0 until itemNodes.length) {
                val item = itemNodes.item(itemIndex) as Element
                items[item.getAttribute("quantity")] = unescape(item.textContent)
            }
            plurals[element.getAttribute("name")] = items
        }
        Catalog(strings, plurals)
    }

    /** 按中文资源解析。 */
    fun zh(text: UiText?): String? = text?.let { resolve(it, CHINESE) }

    /** 按默认（英文）资源解析。 */
    fun en(text: UiText?): String? = text?.let { resolve(it, DEFAULT) }

    fun stringName(id: Int): String = stringNames[id] ?: error("未知的字符串资源 id $id")

    fun resolve(text: UiText, qualifier: String): String = when (text) {
        is UiText.Plain -> text.value
        is UiText.Res -> {
            val name = stringName(text.id)
            val template = catalog(qualifier).strings[name] ?: error("$qualifier 缺少字符串 $name")
            format(template, text.args, qualifier)
        }
        is UiText.Plural -> {
            val name = pluralNames[text.id] ?: error("未知的复数资源 id ${text.id}")
            val items = catalog(qualifier).plurals[name] ?: error("$qualifier 缺少复数 $name")
            val quantity = if (qualifier == DEFAULT && text.count == 1) "one" else "other"
            val template = items[quantity] ?: items.getValue("other")
            format(template, text.args, qualifier)
        }
    }

    private fun format(template: String, args: List<Any?>, qualifier: String): String {
        if (args.isEmpty()) return template
        val resolved = args.map { arg -> if (arg is UiText) resolve(arg, qualifier) else arg ?: "" }
        return String.format(Locale.ROOT, template, *resolved.toTypedArray())
    }

    private fun resourceNames(type: Class<*>): Map<Int, String> =
        type.fields.associate { field -> field.getInt(null) to field.name }

    /** 还原 aapt 的转义：去掉首尾引号，处理 \' \" \n \\ \@ \?。 */
    fun unescape(raw: String): String {
        var text = raw
        if (text.length >= 2 && text.startsWith('"') && text.endsWith('"')) {
            text = text.substring(1, text.length - 1)
        }
        val builder = StringBuilder()
        var index = 0
        while (index < text.length) {
            val char = text[index]
            if (char == '\\' && index + 1 < text.length) {
                when (val next = text[index + 1]) {
                    'n' -> builder.append('\n')
                    't' -> builder.append('\t')
                    else -> builder.append(next)
                }
                index += 2
            } else {
                builder.append(char)
                index += 1
            }
        }
        return builder.toString()
    }
}
