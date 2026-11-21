package com.memoisle.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 默认（英文）与中文资源的键、占位符必须一致，缺翻译时直接失败。 */
class StringsParityTest {
    private val english = TestStrings.catalog(TestStrings.DEFAULT)
    private val chinese = TestStrings.catalog(TestStrings.CHINESE)
    private val placeholder = Regex("""%(\d+)\$[sd]""")
    private val cjk = Regex("""[一-鿿]""")

    private fun placeholders(text: String): Set<String> = placeholder.findAll(text).map { it.value }.toSet()

    @Test
    fun stringKeysMatch() {
        assertTrue("没有读到任何字符串资源", english.strings.isNotEmpty())
        assertEquals(english.strings.keys.sorted(), chinese.strings.keys.sorted())
    }

    @Test
    fun pluralKeysMatch() {
        assertEquals(english.plurals.keys.sorted(), chinese.plurals.keys.sorted())
        english.plurals.forEach { (name, items) ->
            assertTrue("英文复数 $name 缺少 one/other", items.keys.containsAll(listOf("one", "other")))
            assertTrue("中文复数 $name 缺少 other", chinese.plurals.getValue(name).containsKey("other"))
        }
    }

    @Test
    fun placeholdersMatch() {
        english.strings.forEach { (name, text) ->
            assertEquals("占位符不一致：$name", placeholders(text), placeholders(chinese.strings.getValue(name)))
        }
        english.plurals.forEach { (name, items) ->
            val expected = placeholders(items.getValue("other"))
            items.values.forEach { assertEquals("英文复数占位符不一致：$name", expected, placeholders(it)) }
            chinese.plurals.getValue(name).values.forEach {
                assertEquals("中文复数占位符不一致：$name", expected, placeholders(it))
            }
        }
    }

    @Test
    fun englishResourcesHaveNoChinese() {
        // 「中文」是语言选项里中文的自称，任何界面语言下都这样显示。
        val allowed = setOf("language_chinese")
        val leftovers = english.strings.filter { (name, text) -> name !in allowed && cjk.containsMatchIn(text) }.keys +
            english.plurals.filter { (_, items) -> items.values.any { cjk.containsMatchIn(it) } }.keys
        assertEquals(emptySet<String>(), leftovers)
    }

    @Test
    fun translationsAreNotBlank() {
        val blankAllowed = setOf<String>()
        listOf(english, chinese).forEach { catalog ->
            catalog.strings.forEach { (name, text) ->
                assertTrue("文案为空：$name", name in blankAllowed || text.isNotBlank())
            }
        }
    }
}
