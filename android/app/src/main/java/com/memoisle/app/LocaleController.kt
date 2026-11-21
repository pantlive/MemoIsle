package com.memoisle.app

import android.app.Activity
import android.app.LocaleManager
import android.content.Context
import android.content.res.Configuration
import android.content.res.Resources
import android.os.Build
import android.os.LocaleList
import androidx.core.content.edit
import java.util.Locale

/** 界面语言偏好：跟随系统，或手动选择中文 / English。 */
enum class AppLanguage(val tag: String) {
    SYSTEM(""),
    ZH("zh"),
    EN("en"),
    ;

    companion object {
        /** 解析保存的语言标签；空值或无法识别时跟随系统。 */
        fun fromTag(tag: String?): AppLanguage {
            val normalized = tag?.trim()?.lowercase(Locale.ROOT).orEmpty()
            return when {
                normalized.isEmpty() -> SYSTEM
                normalized == "zh" || normalized.startsWith("zh-") || normalized.startsWith("zh_") -> ZH
                normalized == "en" || normalized.startsWith("en-") || normalized.startsWith("en_") -> EN
                else -> SYSTEM
            }
        }
    }
}

/** 保存语言偏好的地方；抽出来便于在 JVM 单元测试里替换。 */
interface LanguagePreferenceStore {
    fun read(): String?

    fun write(tag: String?)
}

private class SharedPreferencesLanguageStore(context: Context) : LanguagePreferenceStore {
    private val preferences = context.getSharedPreferences(LocaleController.PREFERENCES_NAME, Context.MODE_PRIVATE)

    override fun read(): String? = preferences.getString(LocaleController.KEY_LANGUAGE, null)

    override fun write(tag: String?) {
        preferences.edit {
            if (tag.isNullOrEmpty()) remove(LocaleController.KEY_LANGUAGE) else putString(LocaleController.KEY_LANGUAGE, tag)
        }
    }
}

/**
 * 应用内语言切换，不依赖 appcompat：
 * - Android 13+ 交给系统的「应用语言」（LocaleManager），系统设置里也能改，空列表表示跟随系统；
 * - Android 8–12 把偏好存在本机，Activity / Application 在 attachBaseContext 里换成对应语言的 Context。
 */
object LocaleController {
    const val PREFERENCES_NAME = "memoisle_locale"
    const val KEY_LANGUAGE = "language"

    /** 系统语言以中文开头时界面显示中文，其余语言显示英文（与 Web 端一致）。 */
    fun localeFor(language: AppLanguage): Locale? = when (language) {
        AppLanguage.SYSTEM -> null
        AppLanguage.ZH -> Locale.SIMPLIFIED_CHINESE
        AppLanguage.EN -> Locale.ENGLISH
    }

    fun readPreference(store: LanguagePreferenceStore): AppLanguage =
        runCatching { AppLanguage.fromTag(store.read()) }.getOrDefault(AppLanguage.SYSTEM)

    fun writePreference(store: LanguagePreferenceStore, language: AppLanguage) {
        // 写入失败只影响下次启动，本次仍按选择切换。
        runCatching { store.write(language.tag.ifEmpty { null }) }
    }

    fun currentPreference(context: Context): AppLanguage {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val locales = context.getSystemService(LocaleManager::class.java)?.applicationLocales
            if (locales == null || locales.isEmpty) return AppLanguage.SYSTEM
            return AppLanguage.fromTag(locales[0].toLanguageTag())
        }
        return readPreference(SharedPreferencesLanguageStore(context))
    }

    /** 切换语言。Android 13+ 由系统重建 Activity；更早的版本保存后手动重建。 */
    fun setPreference(activity: Activity, language: AppLanguage) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            activity.getSystemService(LocaleManager::class.java)?.applicationLocales =
                if (language == AppLanguage.SYSTEM) {
                    LocaleList.getEmptyLocaleList()
                } else {
                    LocaleList.forLanguageTags(language.tag)
                }
            return
        }
        writePreference(SharedPreferencesLanguageStore(activity), language)
        activity.recreate()
    }

    /** Android 12 及以下：按保存的偏好包一层带语言的 Context；跟随系统时恢复系统语言。 */
    fun wrap(base: Context): Context {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) return base
        val locale = localeFor(readPreference(SharedPreferencesLanguageStore(base)))
        if (locale == null) {
            // 之前手动切过语言时进程里的默认 Locale 已被改掉，跟随系统时改回来。
            Resources.getSystem().configuration.locales.get(0)?.let(Locale::setDefault)
            return base
        }
        Locale.setDefault(locale)
        val configuration = Configuration(base.resources.configuration)
        configuration.setLocales(LocaleList(locale))
        return base.createConfigurationContext(configuration)
    }
}
