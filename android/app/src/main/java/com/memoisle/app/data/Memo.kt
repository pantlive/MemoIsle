package com.memoisle.app.data

import java.time.Instant
import java.time.ZoneOffset
import java.net.URI
import java.util.UUID

enum class SyncState {
    SYNCED,
    PENDING,
    FAILED,
}

data class Memo(
    val id: String?,
    val clientId: String,
    val type: String,
    val title: String,
    val body: String,
    val sourceUrl: String?,
    val sourceTitle: String?,
    val resourceDescription: String? = null,
    val resourceSiteName: String? = null,
    val resourceImageUrl: String? = null,
    val resourceCategory: String? = null,
    val resourceCategoryLabel: String? = null,
    val resourceKind: String? = null,
    val resourceReadingStatus: String? = null,
    val resourceCategoryStatus: String = "none",
    val resourceAutoTags: List<String> = emptyList(),
    val resourceImportFolder: String? = null,
    val linkHealthStatus: String = "unchecked",
    val linkHealthHttpStatus: Int? = null,
    val linkHealthError: String? = null,
    val linkLastCheckedAt: String? = null,
    val linkLastSuccessAt: String? = null,
    val linkEffectiveUrl: String? = null,
    val wordPhonetic: String?,
    val wordMeaning: String?,
    val wordExample: String?,
    val familiarity: Int,
    val reviewCount: Int,
    val lastReviewAt: String?,
    val nextReviewAt: String?,
    val audioMimeType: String?,
    val audioSizeBytes: Int?,
    val audioDurationMs: Int?,
    val transcript: String?,
    val transcriptStatus: String,
    val localAudioPath: String?,
    val tags: List<String>,
    val collections: List<String> = emptyList(),
    val starred: Boolean = false,
    val status: String,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
    val syncState: SyncState,
)

fun Memo.matchesQuery(query: String): Boolean {
    val cleanedQuery = query.trim()
    if (cleanedQuery.isEmpty()) {
        return true
    }
    // 本地搜索覆盖服务端全局搜索提供的同一组用户可见字段。
    val searchableValues = listOfNotNull(
        title,
        body,
        sourceUrl,
        sourceTitle,
        resourceDescription,
        resourceSiteName,
        resourceCategory,
        resourceKind,
        resourceReadingStatus,
        resourceImportFolder,
        wordPhonetic,
        wordMeaning,
        wordExample,
        transcript,
    ) + tags + collections
    return searchableValues.any { value ->
        value.contains(cleanedQuery, ignoreCase = true)
    }
}

fun Memo.isVisibleInLibrary(): Boolean = status != "trashed"

fun normalizeLemma(value: String): String =
    value.trim().lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")

fun List<Memo>.findDuplicateWord(lemma: String, exceptClientId: String? = null): Memo? {
    val normalized = normalizeLemma(lemma)
    if (normalized.isEmpty()) {
        return null
    }
    return firstOrNull { memo ->
        memo.type == TYPE_WORD &&
            memo.isVisibleInLibrary() &&
            memo.clientId != exceptClientId &&
            normalizeLemma(memo.title) == normalized
    }
}

fun Memo.reviewedToday(now: Instant = Instant.now()): Boolean {
    val lastReview = lastReviewAt ?: return false
    return runCatching {
        val lastInstant = Instant.parse(lastReview)
        lastInstant.atZone(ZoneOffset.UTC).toLocalDate() ==
            now.atZone(ZoneOffset.UTC).toLocalDate()
    }.getOrDefault(false)
}

fun Memo.isDueWord(now: Instant = Instant.now()): Boolean {
    if (type != TYPE_WORD || status == "trashed" || reviewedToday(now)) {
        return false
    }
    val dueAt = nextReviewAt
    return dueAt.isNullOrBlank() || runCatching { Instant.parse(dueAt) <= now }.getOrDefault(true)
}

fun Memo.isUnreadResource(now: Instant = Instant.now()): Boolean {
    if (type != TYPE_RESOURCE || status == "trashed" || reviewedToday(now)) {
        return false
    }
    return resourceReadingStatus.isNullOrBlank() || resourceReadingStatus == "unread"
}

fun Memo.isInboxIdea(now: Instant = Instant.now()): Boolean {
    return type == TYPE_IDEA && status == "inbox" && !reviewedToday(now)
}

data class ReviewCounts(
    val wordCount: Int,
    val resourceCount: Int,
    val ideaCount: Int,
) {
    val totalCount: Int get() = wordCount + resourceCount + ideaCount
}

fun List<Memo>.todayReviewCounts(): ReviewCounts = ReviewCounts(
    wordCount = count { it.isDueWord() },
    resourceCount = count { it.isUnreadResource() },
    ideaCount = count { it.isInboxIdea() },
)

fun List<Memo>.todayReviewItems(limit: Int = 10): List<Memo> {
    val words = filter { it.isDueWord() }
    val resources = filter { it.isUnreadResource() }
    val ideas = filter { it.isInboxIdea() }
    val items = mutableListOf<Memo>()
    var index = 0
    while (items.size < limit) {
        var added = false
        listOf(words, resources, ideas).forEach { group ->
            if (index < group.size && items.size < limit) {
                items.add(group[index])
                added = true
            }
        }
        if (!added) {
            break
        }
        index += 1
    }
    return items
}

fun newLocalIdea(body: String): Memo {
    val now = Instant.now().toString()
    return Memo(
        id = null,
        clientId = UUID.randomUUID().toString(),
        type = TYPE_IDEA,
        title = defaultMemoTitle(body),
        body = body.trim(),
        sourceUrl = null,
        sourceTitle = null,
        wordPhonetic = null,
        wordMeaning = null,
        wordExample = null,
        familiarity = 0,
        reviewCount = 0,
        lastReviewAt = null,
        nextReviewAt = null,
        audioMimeType = null,
        audioSizeBytes = null,
        audioDurationMs = null,
        transcript = null,
        transcriptStatus = "none",
        localAudioPath = null,
        tags = emptyList(),
        status = "inbox",
        version = 1,
        createdAt = now,
        updatedAt = now,
        syncState = SyncState.PENDING,
    )
}

fun newLocalResource(url: String, title: String, note: String): Memo {
    val normalizedUrl = requireNotNull(normalizeResourceUrl(url)) {
        "网页资料必须包含有效的网址"
    }
    val cleanedTitle = title.trim().ifEmpty { resourceHost(normalizedUrl) }
    val cleanedNote = note.trim().ifEmpty { normalizedUrl }
    val now = Instant.now().toString()
    return Memo(
        id = null,
        clientId = UUID.randomUUID().toString(),
        type = TYPE_RESOURCE,
        title = cleanedTitle,
        body = cleanedNote,
        sourceUrl = normalizedUrl,
        sourceTitle = cleanedTitle,
        wordPhonetic = null,
        wordMeaning = null,
        wordExample = null,
        familiarity = 0,
        reviewCount = 0,
        lastReviewAt = null,
        nextReviewAt = null,
        audioMimeType = null,
        audioSizeBytes = null,
        audioDurationMs = null,
        transcript = null,
        transcriptStatus = "none",
        localAudioPath = null,
        tags = emptyList(),
        status = "active",
        version = 1,
        createdAt = now,
        updatedAt = now,
        syncState = SyncState.PENDING,
    )
}

fun newLocalWord(
    lemma: String,
    phonetic: String,
    meaning: String,
    example: String,
): Memo {
    val cleanedLemma = lemma.trim()
    require(cleanedLemma.isNotEmpty()) { "英语单词必须包含词形" }
    val cleanedMeaning = meaning.trim()
    val now = Instant.now().toString()
    return Memo(
        id = null,
        clientId = UUID.randomUUID().toString(),
        type = TYPE_WORD,
        title = cleanedLemma,
        body = cleanedMeaning.ifEmpty { cleanedLemma },
        sourceUrl = null,
        sourceTitle = null,
        wordPhonetic = phonetic.trim().ifEmpty { null },
        wordMeaning = cleanedMeaning.ifEmpty { null },
        wordExample = example.trim().ifEmpty { null },
        familiarity = 0,
        reviewCount = 0,
        lastReviewAt = null,
        nextReviewAt = now,
        audioMimeType = null,
        audioSizeBytes = null,
        audioDurationMs = null,
        transcript = null,
        transcriptStatus = "none",
        localAudioPath = null,
        tags = emptyList(),
        status = "active",
        version = 1,
        createdAt = now,
        updatedAt = now,
        syncState = SyncState.PENDING,
    )
}

fun newLocalVoiceIdea(body: String, audioPath: String, durationMs: Int): Memo {
    val resolvedBody = body.trim().ifEmpty { "语音记录" }
    return newLocalIdea(resolvedBody).copy(
        audioMimeType = "audio/mp4",
        audioDurationMs = durationMs,
        transcript = body.trim().ifEmpty { null },
        transcriptStatus = if (body.isBlank()) "not_requested" else "manual",
        localAudioPath = audioPath,
    )
}

data class ClipboardWordDraft(
    val lemma: String,
    val phonetic: String? = null,
    val meaning: String? = null,
    val example: String? = null,
)

fun parseClipboardWord(raw: String): ClipboardWordDraft? {
    val text = raw.replace('\u00a0', ' ').replace("\r\n", "\n").trim()
    if (text.isEmpty() || isClipboardUrl(text) || isClipboardUrl(text.substringBefore(' '))) {
        return null
    }
    val lines = text.split('\n').map(String::trim).filter(String::isNotEmpty)
    if (lines.isEmpty()) {
        return null
    }
    var firstLine = lines.first()
    var phonetic: String? = null
    val phoneticMatch = Regex("""([/\[])([^/\[\]]{1,80})\1""").find(firstLine)
    if (phoneticMatch != null) {
        phonetic = "/${phoneticMatch.groupValues[2]}/".take(120)
        firstLine = (
            firstLine.substring(0, phoneticMatch.range.first) + " " +
                firstLine.substring(phoneticMatch.range.last + 1)
            ).replace(Regex("\\s+"), " ").trim()
    }
    var lemma = firstLine
    var meaning = lines.drop(1).joinToString("\n").trim().ifEmpty { null }
    val mixed = Regex(
        """^([A-Za-z][A-Za-z0-9'’.\-]*(?:[\s-][A-Za-z][A-Za-z0-9'’.\-]*){0,7})\s+([^\s].+)$""",
    ).find(firstLine)
    if (mixed != null && hasCjk(mixed.groupValues[2]) && !hasCjk(mixed.groupValues[1])) {
        lemma = mixed.groupValues[1].trim()
        meaning = listOfNotNull(mixed.groupValues[2].trim(), meaning)
            .filter { it.isNotEmpty() }
            .joinToString("\n")
            .ifEmpty { null }
    }
    lemma = lemma.replace(Regex("\\s+"), " ").trim()
    if (!isPlausibleClipboardLemma(lemma)) {
        return null
    }
    return ClipboardWordDraft(
        lemma = lemma.take(200).trim(),
        phonetic = phonetic,
        meaning = meaning?.take(5_000),
    )
}

private fun isClipboardUrl(value: String): Boolean {
    val cleaned = value.trim()
    return cleaned.startsWith("http://", ignoreCase = true) ||
        cleaned.startsWith("https://", ignoreCase = true) ||
        cleaned.startsWith("www.", ignoreCase = true) ||
        Regex("""^[a-z0-9.-]+\.[a-z]{2,}([/:?#].*)?$""", RegexOption.IGNORE_CASE)
            .matches(cleaned)
}

private fun isPlausibleClipboardLemma(lemma: String): Boolean {
    if (lemma.isEmpty() || lemma.length > 80 || isClipboardUrl(lemma)) {
        return false
    }
    if (lemma.last() in charArrayOf('.', '!', '?', '。', '！', '？')) {
        return false
    }
    if (!lemma.any { it in 'A'..'Z' || it in 'a'..'z' }) {
        return false
    }
    return lemma.split(Regex("\\s+")).count { it.isNotEmpty() } <= 8
}

private fun hasCjk(value: String): Boolean =
    value.any { it.code in 0x3400..0x9FFF }

fun defaultMemoTitle(body: String): String {
    val firstLine = body.lineSequence().firstOrNull { it.isNotBlank() }?.trim().orEmpty()
    if (firstLine.isEmpty()) {
        return "灵感"
    }
    return if (firstLine.length <= 80) firstLine else "${firstLine.take(77)}..."
}

fun normalizeResourceUrl(value: String): String? {
    val cleaned = value.trim()
    if (cleaned.isEmpty()) {
        return null
    }
    val candidate = if (cleaned.startsWith("http://", ignoreCase = true) ||
        cleaned.startsWith("https://", ignoreCase = true)
    ) {
        cleaned
    } else {
        "https://$cleaned"
    }
    return runCatching {
        val uri = URI(candidate)
        if (uri.scheme.lowercase() !in setOf("http", "https") || uri.host.isNullOrBlank()) {
            null
        } else {
            uri.toASCIIString()
        }
    }.getOrNull()
}

fun resourceHost(url: String): String {
    return runCatching {
        URI(url).host.orEmpty().removePrefix("www.")
    }.getOrDefault("网页资料").ifEmpty { "网页资料" }
}

fun resourceCategoryLabel(category: String?, customLabel: String? = null): String {
    if (!customLabel.isNullOrBlank()) {
        return customLabel
    }
    return when (category) {
        "learning" -> "学习资料"
        "article" -> "文章阅读"
        "media" -> "视频与音频"
        "tool" -> "工具与服务"
        "book_paper" -> "书籍与论文"
        "product" -> "商品与好物"
        "other" -> "其他"
        else -> "分类中"
    }
}

fun resourceKindLabel(kind: String?): String = when (kind) {
    "article" -> "文章"
    "video" -> "视频"
    "course" -> "课程"
    "tool" -> "工具"
    "book" -> "书籍"
    else -> "其他"
}

fun resourceReadingStatusLabel(status: String?): String = when (status) {
    "reading" -> "阅读中"
    "completed" -> "已完成"
    "archived" -> "已归档"
    else -> "未读"
}

fun linkHealthLabel(status: String): String = when (status) {
    "healthy" -> "网页正常"
    "redirected" -> "网址已跳转"
    "changed" -> "网页有更新"
    "auth_required" -> "需要登录"
    "temporary_failure" -> "暂时无法访问"
    "failed" -> "网页已失效"
    "ignored" -> "已忽略巡检"
    else -> "等待检查"
}

const val TYPE_IDEA = "idea"
const val TYPE_RESOURCE = "resource"
const val TYPE_WORD = "word"
