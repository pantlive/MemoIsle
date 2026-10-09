package com.memoisle.app.audio

import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WordPronouncerTest {
    @Test
    fun youdaoVoiceUrlUsesAmericanType() {
        assertEquals(
            "https://dict.youdao.com/dictvoice?audio=good&type=2",
            youdaoVoiceUrl("good", Locale.US),
        )
    }

    @Test
    fun youdaoVoiceUrlUsesBritishType() {
        assertEquals(
            "https://dict.youdao.com/dictvoice?audio=good&type=1",
            youdaoVoiceUrl("good", Locale.UK),
        )
    }

    @Test
    fun youdaoVoiceUrlEncodesPhrases() {
        val url = youdaoVoiceUrl("look forward to", Locale.US)
        assertTrue(url.contains("audio=look%20forward%20to"))
        assertTrue(url.endsWith("&type=2"))
    }
}
