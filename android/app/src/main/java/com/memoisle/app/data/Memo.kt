package com.memoisle.app.data

import java.time.Instant
import java.time.ZoneOffset
import java.net.URI
import java.util.Locale
import java.util.UUID
import com.memoisle.app.R
import com.memoisle.app.ui.UiText
import com.memoisle.app.ui.UiTextException

enum class SyncState {
    SYNCED,
    PENDING,
    FAILED,
    CONFLICT,
}

data class MemoSyncCursor(
    val timestamp: String,
    val memoId: String?,
)

data class MemoDeletion(val memoId: String, val clientId: String)

/** 删除通知只匹配同一条收藏，避免清理仍未上传的新建内容。 */
fun Memo.matchesDeletion(deletion: MemoDeletion): Boolean =
    id == deletion.memoId || clientId == deletion.clientId

data class Memo(
    val id: String?,
    val clientId: String,
    val type: String,
    val title: String,
    val body: String,
    val sourceUrl: String?,
    val sourceTitle: String?,
    val resourceDescription: String? = null,
    // 服务端大模型写的用途简介，列表和快速访问优先显示。
    val resourceAiSummary: String? = null,
    val resourceSiteName: String? = null,
    val resourceImageUrl: String? = null,
    val resourceCategory: String? = null,
    val resourceCategoryLabel: String? = null,
    val resourceCategories: List<String> = emptyList(),
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
    // 图片收藏的元数据由服务端在上传后返回，未上传时全部为空。
    val imageMimeType: String? = null,
    val imageSizeBytes: Int? = null,
    val imageWidth: Int? = null,
    val imageHeight: Int? = null,
    val imageHash: String? = null,
    // 图片 OCR 结果由服务端识别，Android 只读缓存并在详情里展示。
    val imageOcrText: String? = null,
    val imageOcrStatus: String = "none",
    val imageOcrError: String? = null,
    val imageOcrSource: String? = null,
    val imageAutoTags: List<String> = emptyList(),
    val imageOcrUpdatedAt: String? = null,
    val tags: List<String>,
    val collections: List<String> = emptyList(),
    val starred: Boolean = false,
    val status: String,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
    val syncState: SyncState,
    val deletedAt: String? = null,
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
        resourceAiSummary,
        resourceSiteName,
        resourceCategory,
        resourceKind,
        resourceReadingStatus,
        resourceImportFolder,
        wordPhonetic,
        wordMeaning,
        wordExample,
        transcript,
        imageOcrText,
    ) + tags + collections + imageAutoTags
    return searchableValues.any { value ->
        value.contains(cleanedQuery, ignoreCase = true)
    }
}

fun Memo.isVisibleInLibrary(): Boolean = status != "trashed"

fun Memo.isInTrash(): Boolean = status == "trashed"

fun Memo.trashDaysRemaining(
    now: Instant = Instant.now(),
    retentionDays: Int = 30,
): Int {
    val start = runCatching {
        Instant.parse(deletedAt ?: updatedAt)
    }.getOrNull() ?: return 0
    val remainingMs = retentionDays * 24L * 60L * 60L * 1000L -
        (now.toEpochMilli() - start.toEpochMilli())
    if (remainingMs <= 0L) {
        return 0
    }
    val dayMs = 24L * 60L * 60L * 1000L
    return ((remainingMs + dayMs - 1L) / dayMs).toInt()
}

private val irregularLemmas = mapOf(
    "used" to "use",
    "am" to "be",
    "are" to "be",
    "being" to "be",
    "been" to "be",
    "was" to "be",
    "were" to "be",
    "is" to "be",
    "dying" to "die",
    "lying" to "lie",
    "tying" to "tie",
    "ran" to "run",
    "does" to "do",
    "did" to "do",
    "done" to "do",
    "has" to "have",
    "had" to "have",
    "went" to "go",
    "gone" to "go",
    "goes" to "go",
    "bought" to "buy",
    "brought" to "bring",
    "came" to "come",
    "drove" to "drive",
    "driven" to "drive",
    "made" to "make",
    "took" to "take",
    "taken" to "take",
    "wrote" to "write",
    "written" to "write",
    "children" to "child",
    "men" to "man",
    "women" to "woman",
    "mice" to "mouse",
    "feet" to "foot",
    "teeth" to "tooth",
    "people" to "person",
    "movies" to "movie",
    "cookies" to "cookie",
    "loves" to "love",
    "lives" to "live",
    "leaves" to "leave",
    "lived" to "live",
    "buses" to "bus",
    "shoes" to "shoe",
    "toes" to "toe",
    "pies" to "pie",
    "ties" to "tie",
    "lies" to "lie",
    "dies" to "die",
    "news" to "news",
    "always" to "always",
    "means" to "means",
    "mathematics" to "mathematics",
    "physics" to "physics",
    "politics" to "politics",
    "economics" to "economics",
    "ethics" to "ethics",
)

private val silentEStems = mapOf(
    "com" to "come",
    "decid" to "decide",
    "driv" to "drive",
    "giv" to "give",
    "hav" to "have",
    "lik" to "like",
    "liv" to "live",
    "lov" to "love",
    "mak" to "make",
    "mov" to "move",
    "rid" to "ride",
    "ris" to "rise",
    "sav" to "save",
    "tak" to "take",
    "us" to "use",
    "writ" to "write",
)

private val commonAdjectiveLemmas = setOf(
    "bad",
    "big",
    "bright",
    "busy",
    "cheap",
    "clean",
    "clear",
    "cold",
    "dark",
    "deep",
    "early",
    "easy",
    "fast",
    "good",
    "happy",
    "hard",
    "heavy",
    "high",
    "hot",
    "kind",
    "large",
    "late",
    "light",
    "long",
    "loud",
    "low",
    "new",
    "nice",
    "old",
    "quick",
    "quiet",
    "safe",
    "short",
    "simple",
    "slow",
    "small",
    "soft",
    "strong",
    "warm",
    "weak",
    "wide",
    "young",
)

private val comparativeSilentEStems = mapOf(
    "larg" to "large",
    "lat" to "late",
    "nic" to "nice",
    "saf" to "safe",
    "simpl" to "simple",
    "wid" to "wide",
)

// 单音节「辅音 + 单元音 + 辅音」词干：hop、bas、dat。与服务端 _verb_stem 保持一致。
private val singleSyllableCvc = Regex("^[^aeiou]*[aeiou][^aeiouwxy]$")

/**
 * 去掉 -ed / -ing 后还原动词原形：双写辅音还原（stopped → stop），但原词本身
 * 双写时保持（added → add）；没有双写的单音节 CVC 词干补回 e（hoped → hope）。
 */
private fun verbStem(stem: String): String = when {
    stem.endsWith("e") -> stem
    stem.length > 1 && stem.last() == stem[stem.lastIndex - 1] && stem.last() !in "lsz" ->
        if (stem.length > 3) stem.dropLast(1) else stem
    singleSyllableCvc.matches(stem) -> stem + "e"
    else -> stem
}

fun normalizeLemma(value: String): String {
    val normalized = value.trim().lowercase(Locale.ROOT)
        .split(Regex("\\s+"))
        .filter { it.isNotEmpty() }
        .joinToString(" ")
    if (normalized.isEmpty() || normalized.contains(" ")) {
        return normalized
    }
    irregularLemmas[normalized]?.let { return it }
    return when {
        normalized.endsWith("ying") && normalized.length > 5 -> normalized.dropLast(3)
        normalized.endsWith("ies") && normalized.length > 4 ->
            normalized.dropLast(3) + "y"
        normalized.endsWith("ves") && normalized.length > 4 -> normalized.dropLast(1)
        normalized.endsWith("ches") ||
            normalized.endsWith("shes") ||
            normalized.endsWith("sses") ||
            normalized.endsWith("xes") ||
            normalized.endsWith("zes") -> normalized.dropLast(2)
        normalized.endsWith("oes") && normalized.length > 4 -> normalized.dropLast(2)
        normalized.endsWith("ses") && normalized.length > 4 -> normalized.dropLast(1)
        normalized.endsWith("s") &&
            normalized.length > 3 &&
            !normalized.endsWith("ss") &&
            !normalized.endsWith("us") &&
            !normalized.endsWith("is") -> normalized.dropLast(1)
        normalized.endsWith("ing") && normalized.length > 5 -> {
            val stem = normalized.dropLast(3)
            silentEStems[stem] ?: verbStem(stem)
        }
        normalized.endsWith("ied") && normalized.length > 4 ->
            normalized.dropLast(3) + "y"
        normalized.endsWith("ed") && normalized.length > 4 -> {
            val stem = normalized.dropLast(2)
            silentEStems[stem] ?: verbStem(stem)
        }
        normalized.endsWith("iest") && normalized.length > 5 -> {
            val candidate = normalized.dropLast(4) + "y"
            if (candidate in commonAdjectiveLemmas) candidate else normalized
        }
        normalized.endsWith("ier") && normalized.length > 4 -> {
            val candidate = normalized.dropLast(3) + "y"
            if (candidate in commonAdjectiveLemmas) candidate else normalized
        }
        normalized.endsWith("est") && normalized.length > 5 -> {
            var candidate = normalized.dropLast(3)
            if (candidate.length > 1 && candidate.last() == candidate[candidate.lastIndex - 1]) {
                candidate = candidate.dropLast(1)
            }
            when {
                candidate in commonAdjectiveLemmas -> candidate
                comparativeSilentEStems.containsKey(candidate) ->
                    comparativeSilentEStems.getValue(candidate)
                else -> normalized
            }
        }
        normalized.endsWith("er") && normalized.length > 4 -> {
            var candidate = normalized.dropLast(2)
            if (candidate.length > 1 && candidate.last() == candidate[candidate.lastIndex - 1]) {
                candidate = candidate.dropLast(1)
            }
            when {
                candidate in commonAdjectiveLemmas -> candidate
                comparativeSilentEStems.containsKey(candidate) ->
                    comparativeSilentEStems.getValue(candidate)
                else -> normalized
            }
        }
        else -> normalized
    }
}

fun List<Memo>.missingFromRemote(remoteIds: Set<String>): List<Memo> =
    filter { memo -> memo.id != null && memo.id !in remoteIds }

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
    val normalizedUrl = normalizeResourceUrl(url)
        ?: throw UiTextException(UiText.res(R.string.memo_error_resource_url_required))
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
    if (cleanedLemma.isEmpty()) throw UiTextException(UiText.res(R.string.memo_error_word_lemma_required))
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
    val resolvedBody = body.trim().ifEmpty { ContentDefaults.voiceBody }
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
    if (
        text.isEmpty() ||
        isClipboardUrl(text) ||
        isClipboardUrl(text.substringBefore(' '))
    ) {
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
        """^([A-Za-z][A-Za-z0-9'’.\-]*(?:[\s-][A-Za-z][A-Za-z0-9'’.\-]*){0,5})\s+([^\s].+)$""",
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
        cleaned.startsWith("file:", ignoreCase = true) ||
        cleaned.startsWith("www.", ignoreCase = true) ||
        Regex("""^[a-z0-9.-]+\.[a-z]{2,}([/:?#].*)?$""", RegexOption.IGNORE_CASE)
            .matches(cleaned)
}

private fun isPlausibleClipboardLemma(lemma: String): Boolean {
    if (lemma.isEmpty() || lemma.length > 80 || isClipboardUrl(lemma)) {
        return false
    }
    if (hasCjk(lemma) || lemma.contains('/') || lemma.contains('\\')) {
        return false
    }
    if (lemma.contains('_') || lemma.contains(':')) {
        return false
    }
    if (Regex("""\.[a-z0-9]{1,8}$""", RegexOption.IGNORE_CASE).containsMatchIn(lemma)) {
        return false
    }
    if (lemma.last() in charArrayOf('.', '!', '?', '。', '！', '？')) {
        return false
    }
    if (
        !Regex(
            """^[A-Za-z][A-Za-z0-9'’.\-]*(?:[ \-][A-Za-z][A-Za-z0-9'’.\-]*){0,5}$""",
        ).matches(lemma)
    ) {
        return false
    }
    return lemma.split(Regex("\\s+")).count { it.isNotEmpty() } <= 6
}

private fun hasCjk(value: String): Boolean =
    value.any { it.code in 0x3400..0x9FFF }

fun defaultMemoTitle(body: String): String {
    val firstLine = body.lineSequence().firstOrNull { it.isNotBlank() }?.trim().orEmpty()
    if (firstLine.isEmpty()) {
        return ContentDefaults.ideaTitle
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
    }.getOrDefault(ContentDefaults.resourceTitle).ifEmpty { ContentDefaults.resourceTitle }
}

fun Memo.assignedCategoryCodes(): List<String> =
    resourceCategories.ifEmpty { listOfNotNull(resourceCategory) }

/** 自定义分类名是用户内容，原样显示；预置分类按界面语言显示。 */
fun resourceCategoryLabel(category: String?, customLabel: String? = null): UiText {
    if (!customLabel.isNullOrBlank()) {
        return UiText.plain(customLabel)
    }
    return UiText.res(
        when (category) {
            "learning" -> R.string.resource_category_learning
            "article" -> R.string.resource_category_article
            "media" -> R.string.resource_category_media
            "tool" -> R.string.resource_category_tool
            "book_paper" -> R.string.resource_category_book_paper
            "product" -> R.string.resource_category_product
            "other" -> R.string.common_other
            else -> R.string.resource_category_pending
        },
    )
}

fun resourceKindLabel(kind: String?): UiText = UiText.res(
    when (kind) {
        "article" -> R.string.resource_kind_article
        "video" -> R.string.resource_kind_video
        "course" -> R.string.resource_kind_course
        "tool" -> R.string.resource_kind_tool
        "book" -> R.string.resource_kind_book
        else -> R.string.common_other
    },
)

fun resourceReadingStatusLabel(status: String?): UiText = UiText.res(
    when (status) {
        "reading" -> R.string.resource_reading_reading
        "completed" -> R.string.resource_reading_completed
        "archived" -> R.string.resource_reading_archived
        else -> R.string.resource_reading_unread
    },
)

fun linkHealthLabel(status: String): UiText = UiText.res(
    when (status) {
        "healthy" -> R.string.link_health_healthy
        "redirected" -> R.string.link_health_redirected
        "changed" -> R.string.link_health_changed
        "auth_required" -> R.string.link_health_auth_required
        "temporary_failure" -> R.string.link_health_temporary_failure
        "failed" -> R.string.link_health_failed
        "ignored" -> R.string.link_health_ignored
        else -> R.string.link_health_pending
    },
)

const val TYPE_IDEA = "idea"
const val TYPE_RESOURCE = "resource"
const val TYPE_WORD = "word"
const val TYPE_IMAGE = "image"

/**
 * 新建内容时写进数据里的默认标题 / 正文（保存后就是用户内容，不再随语言变化）。
 * 按创建时的界面语言填写：MainActivity 启动（含切换语言后重建）时用当前语言的资源更新。
 */
object ContentDefaults {
    @Volatile var ideaTitle: String = "Idea"
    @Volatile var voiceBody: String = "Voice note"
    @Volatile var resourceTitle: String = "Web resource"
    @Volatile var imageTitle: String = "Image"
    @Volatile var meetingRecording: String = "Meeting recording"
    @Volatile var voiceRecording: String = "Voice idea"
    @Volatile var untitled: String = "Untitled"
    @Volatile var otherProvider: String = "Other"
}

/** 会议录音的数据标签（与 Web 端约定的固定值），是数据标记而不是界面文案，不翻译。 */
const val MEETING_TAG = "会议"

val DEFAULT_IMAGE_MEMO_TITLE: String
    get() = ContentDefaults.imageTitle
const val MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024

private val supportedImageMimeTypes = mapOf(
    "image/png" to "image/png",
    "image/jpeg" to "image/jpeg",
    "image/jpg" to "image/jpeg",
    "image/webp" to "image/webp",
    "image/gif" to "image/gif",
)

private val imageExtensionMimeTypes = mapOf(
    "png" to "image/png",
    "jpg" to "image/jpeg",
    "jpeg" to "image/jpeg",
    "webp" to "image/webp",
    "gif" to "image/gif",
)

fun Memo.isImage(): Boolean = type == TYPE_IMAGE

fun Memo.hasUploadedImage(): Boolean = imageMimeType != null

/**
 * 归一化图片 MIME，服务端只接受 PNG/JPEG/WebP/GIF，无法识别时返回 null。
 */
fun normalizeImageMimeType(raw: String?): String? {
    val cleaned = raw?.substringBefore(';')?.trim()?.lowercase(Locale.ROOT).orEmpty()
    return supportedImageMimeTypes[cleaned]
}

/**
 * 从文件名推断图片 MIME；相册内容提供方偶尔返回空的 Content-Type。
 */
fun imageMimeTypeFromFileName(fileName: String?): String? {
    val name = fileName?.trim().orEmpty()
    val separatorIndex = name.lastIndexOf('.')
    if (separatorIndex <= 0 || separatorIndex == name.lastIndex) {
        return null
    }
    return imageExtensionMimeTypes[name.substring(separatorIndex + 1).lowercase(Locale.ROOT)]
}

fun imageFileExtensionForMimeType(mimeType: String?): String? = when (normalizeImageMimeType(mimeType)) {
    "image/png" -> "png"
    "image/jpeg" -> "jpg"
    "image/webp" -> "webp"
    "image/gif" -> "gif"
    else -> null
}

private val audioFileExtensions = mapOf(
    "audio/mp4" to "m4a",
    "audio/x-m4a" to "m4a",
    "audio/m4a" to "m4a",
    "audio/mpeg" to "mp3",
    "audio/ogg" to "ogg",
    "audio/webm" to "webm",
    "audio/wav" to "wav",
    "audio/x-wav" to "wav",
)

fun audioFileExtensionForMimeType(mimeType: String?): String? {
    val normalized = mimeType?.substringBefore(';')?.trim()?.lowercase(Locale.ROOT) ?: return null
    return audioFileExtensions[normalized]
}

/** 保存录音时使用可读标题和真实容器扩展名，会议录音与普通语音灵感共用。 */
fun audioDownloadFileName(memo: Memo): String {
    val extension = audioFileExtensionForMimeType(memo.audioMimeType) ?: "audio"
    // 「会议」标签是数据标记（Web 端会议模式创建时写入），不随界面语言变化。
    val fallback = if (MEETING_TAG in memo.tags) ContentDefaults.meetingRecording else ContentDefaults.voiceRecording
    val title = memo.title.trim()
        .replace(Regex("[\\\\/:*?\"<>|]"), "_")
        .trim()
        .take(80)
        .ifBlank { fallback }
    val date = memo.createdAt.substringBefore('T').takeIf { it.length == 10 } ?: "record"
    return "$title-$date.$extension"
}

fun imageMemoTitleFromFileName(displayName: String?): String {
    val fileName = displayName
        ?.substringAfterLast('/')
        ?.substringAfterLast('\\')
        ?.trim()
        .orEmpty()
    val withoutExtension = fileName.substringBeforeLast('.', fileName).trim()
    val title = withoutExtension.ifEmpty { DEFAULT_IMAGE_MEMO_TITLE }
    return if (title.length <= 200) title else title.take(200)
}

fun newLocalImage(
    title: String,
    body: String,
    mimeType: String?,
    sizeBytes: Int?,
): Memo {
    val now = Instant.now().toString()
    return Memo(
        id = null,
        clientId = UUID.randomUUID().toString(),
        type = TYPE_IMAGE,
        title = title.trim().ifEmpty { DEFAULT_IMAGE_MEMO_TITLE }.take(200),
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
        imageMimeType = mimeType,
        imageSizeBytes = sizeBytes,
        tags = emptyList(),
        status = "active",
        version = 1,
        createdAt = now,
        updatedAt = now,
        syncState = SyncState.PENDING,
    )
}

fun imageDimensionsLabel(width: Int?, height: Int?): UiText? {
    if (width == null || height == null || width <= 0 || height <= 0) {
        return null
    }
    return UiText.res(R.string.image_dimensions_px, width, height)
}

/**
 * 服务端图片 OCR 状态的可读文案，未知状态按未识别处理。
 */
fun Memo.imageOcrStatusLabel(): UiText = UiText.res(
    when (imageOcrStatus) {
        "pending" -> R.string.image_ocr_pending
        "processing" -> R.string.image_ocr_processing
        "ready" -> R.string.image_ocr_ready
        "failed" -> R.string.image_ocr_failed
        "disabled" -> R.string.image_ocr_disabled
        else -> R.string.image_ocr_none
    },
)

/**
 * OCR 结果来源文案，没有来源时返回 null。
 */
fun Memo.imageOcrSourceLabel(): UiText? = when (imageOcrSource) {
    "local" -> UiText.res(R.string.image_ocr_source_local)
    "llm" -> UiText.res(R.string.image_ocr_source_llm)
    else -> null
}

fun formatFileSize(bytes: Int?): String? {
    if (bytes == null || bytes < 0) {
        return null
    }
    return when {
        bytes < 1024 -> "$bytes B"
        bytes < 1024 * 1024 -> String.format(Locale.ROOT, "%.1f KB", bytes / 1024.0)
        else -> String.format(Locale.ROOT, "%.1f MB", bytes / (1024.0 * 1024.0))
    }
}
