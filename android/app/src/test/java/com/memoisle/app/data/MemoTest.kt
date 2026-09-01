package com.memoisle.app.data

import org.junit.Assert.assertEquals
import org.junit.Test

class MemoTest {
    @Test
    fun defaultTitleUsesFirstNonEmptyLine() {
        val title = defaultMemoTitle("\n  先保存灵感  \n再整理")
        assertEquals("先保存灵感", title)
    }

    @Test
    fun defaultTitleLimitsLength() {
        val title = defaultMemoTitle("想".repeat(100))
        assertEquals(80, title.length)
        assertEquals("...", title.takeLast(3))
    }

    @Test
    fun normalizeResourceUrlAddsHttpsScheme() {
        val url = normalizeResourceUrl("pytorch.org/tutorials/")
        assertEquals("https://pytorch.org/tutorials/", url)
    }

    @Test
    fun localResourceUsesHostAsFallbackTitle() {
        val memo = newLocalResource("https://www.example.com/learn", "", "")
        assertEquals(TYPE_RESOURCE, memo.type)
        assertEquals("example.com", memo.title)
        assertEquals(memo.sourceUrl, memo.body)
    }

    @Test
    fun localWordKeepsLearningFields() {
        val memo = newLocalWord(
            lemma = "serendipity",
            phonetic = "/ˌserənˈdɪpəti/",
            meaning = "机缘巧合",
            example = "We met by serendipity.",
        )
        assertEquals(TYPE_WORD, memo.type)
        assertEquals("机缘巧合", memo.wordMeaning)
        assertEquals(0, memo.familiarity)
    }

    @Test
    fun localVoiceIdeaKeepsAudioDraft() {
        val memo = newLocalVoiceIdea("散步时想到的方案", "/tmp/voice.m4a", 2_500)
        assertEquals("audio/mp4", memo.audioMimeType)
        assertEquals(2_500, memo.audioDurationMs)
        assertEquals("manual", memo.transcriptStatus)
    }

    @Test
    fun searchMatchesDifferentMemoFields() {
        val resource = newLocalResource(
            url = "https://example.com/neural-networks",
            title = "深度学习课程",
            note = "稍后整理",
        ).copy(tags = listOf("学习资料"))
        val word = newLocalWord(
            lemma = "serendipity",
            phonetic = "/ˌserənˈdɪpəti/",
            meaning = "机缘巧合",
            example = "A fortunate discovery.",
        )

        assertEquals(true, resource.matchesQuery("NEURAL"))
        assertEquals(true, resource.matchesQuery("学习资料"))
        assertEquals(true, word.matchesQuery("机缘巧合"))
        assertEquals(false, word.matchesQuery("PyTorch"))
    }

    @Test
    fun resourceSearchIncludesAutomaticMetadataAndStatusLabels() {
        val resource = newLocalResource(
            url = "https://example.com/course",
            title = "课程",
            note = "稍后阅读",
        ).copy(
            resourceDescription = "张量与自动求导入门",
            resourceSiteName = "学习站",
            resourceCategory = "learning",
            resourceAutoTags = listOf("深度学习"),
            linkHealthStatus = "failed",
        )

        assertEquals(true, resource.matchesQuery("自动求导"))
        assertEquals(true, resource.matchesQuery("学习站"))
        assertEquals(true, resource.matchesQuery("learning"))
        assertEquals("学习资料", resourceCategoryLabel(resource.resourceCategory))
        assertEquals("网页已失效", linkHealthLabel(resource.linkHealthStatus))
    }

    @Test
    fun trashedMemoIsHiddenFromLibrary() {
        val active = newLocalIdea("保留内容")
        val trashed = active.copy(status = "trashed")

        assertEquals(true, active.isVisibleInLibrary())
        assertEquals(false, trashed.isVisibleInLibrary())
    }
}
