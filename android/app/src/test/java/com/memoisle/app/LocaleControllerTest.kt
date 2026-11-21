package com.memoisle.app

import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LocaleControllerTest {
    private class MemoryStore(var value: String? = null) : LanguagePreferenceStore {
        override fun read(): String? = value

        override fun write(tag: String?) {
            value = tag
        }
    }

    private class BrokenStore : LanguagePreferenceStore {
        override fun read(): String? = throw IllegalStateException("denied")

        override fun write(tag: String?) = throw IllegalStateException("denied")
    }

    @Test
    fun parsesLanguageTags() {
        assertEquals(AppLanguage.SYSTEM, AppLanguage.fromTag(null))
        assertEquals(AppLanguage.SYSTEM, AppLanguage.fromTag(""))
        assertEquals(AppLanguage.SYSTEM, AppLanguage.fromTag("  "))
        assertEquals(AppLanguage.ZH, AppLanguage.fromTag("zh"))
        assertEquals(AppLanguage.ZH, AppLanguage.fromTag("zh-CN"))
        assertEquals(AppLanguage.ZH, AppLanguage.fromTag("zh-Hans-CN"))
        assertEquals(AppLanguage.ZH, AppLanguage.fromTag("ZH_tw"))
        assertEquals(AppLanguage.EN, AppLanguage.fromTag("en"))
        assertEquals(AppLanguage.EN, AppLanguage.fromTag("en-US"))
        // 不支持的语言、形似但不是中文的标签都回退到跟随系统。
        assertEquals(AppLanguage.SYSTEM, AppLanguage.fromTag("ja"))
        assertEquals(AppLanguage.SYSTEM, AppLanguage.fromTag("zhx"))
    }

    @Test
    fun readsAndWritesPreference() {
        val store = MemoryStore()
        assertEquals(AppLanguage.SYSTEM, LocaleController.readPreference(store))

        LocaleController.writePreference(store, AppLanguage.EN)
        assertEquals("en", store.value)
        assertEquals(AppLanguage.EN, LocaleController.readPreference(store))

        LocaleController.writePreference(store, AppLanguage.ZH)
        assertEquals(AppLanguage.ZH, LocaleController.readPreference(store))

        // 跟随系统时清掉保存的值。
        LocaleController.writePreference(store, AppLanguage.SYSTEM)
        assertNull(store.value)
        assertEquals(AppLanguage.SYSTEM, LocaleController.readPreference(store))
    }

    @Test
    fun brokenStorageFallsBackToSystem() {
        val store = BrokenStore()
        assertEquals(AppLanguage.SYSTEM, LocaleController.readPreference(store))
        // 写入失败不抛出，只影响下次启动。
        LocaleController.writePreference(store, AppLanguage.EN)
        assertEquals(AppLanguage.SYSTEM, LocaleController.readPreference(MemoryStore("fr")))
    }

    @Test
    fun mapsLanguageToLocale() {
        assertNull(LocaleController.localeFor(AppLanguage.SYSTEM))
        assertEquals("zh", LocaleController.localeFor(AppLanguage.ZH)?.language)
        assertEquals(Locale.ENGLISH, LocaleController.localeFor(AppLanguage.EN))
    }
}
