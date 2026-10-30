package com.memoisle.app.data

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

class MemoTest {
    @Test
    fun permanentDeletionMatchesRemoteIdOrOriginalClientId() {
        val memo = newLocalIdea("删除同步测试").copy(id = "remote-a", clientId = "client-a")
        assertEquals(true, memo.matchesDeletion(MemoDeletion("remote-a", "client-other")))
        assertEquals(true, memo.matchesDeletion(MemoDeletion("remote-other", "client-a")))
        assertEquals(false, memo.matchesDeletion(MemoDeletion("remote-other", "client-other")))
        assertEquals(false, newLocalIdea("离线新建").matchesDeletion(MemoDeletion("remote-a", "client-a")))
    }
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
    fun assignedCategoryCodesKeepsExtrasAndFallsBackToPrimary() {
        val withExtras = newLocalResource(
            url = "https://example.com/course",
            title = "课程",
            note = "",
        ).copy(
            resourceCategory = "learning",
            resourceCategories = listOf("learning", "article"),
        )
        val primaryOnly = withExtras.copy(resourceCategories = emptyList())

        assertEquals(listOf("learning", "article"), withExtras.assignedCategoryCodes())
        assertEquals(listOf("learning"), primaryOnly.assignedCategoryCodes())
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
    fun missingFromRemoteKeepsLocalOnlyDrafts() {
        val localDraft = newLocalIdea("还没上传")
        val kept = newLocalIdea("服务端仍在").copy(id = "remote-keep")
        val stale = newLocalIdea("服务端已删").copy(id = "remote-gone")

        val missing = listOf(localDraft, kept, stale).missingFromRemote(
            setOf("remote-keep"),
        )

        assertEquals(listOf(stale), missing)
    }

    @Test
    fun trashedMemoIsHiddenFromLibrary() {
        val active = newLocalIdea("保留内容")
        val trashed = active.copy(status = "trashed")

        assertEquals(true, active.isVisibleInLibrary())
        assertEquals(false, trashed.isVisibleInLibrary())
        assertEquals(true, trashed.isInTrash())
    }

    @Test
    fun trashDaysRemainingUsesDeletedAt() {
        val now = Instant.parse("2026-09-04T00:00:00Z")
        val trashed = newLocalIdea("回收站内容").copy(
            status = "trashed",
            deletedAt = "2026-08-25T00:00:00Z",
            updatedAt = "2026-08-25T00:00:00Z",
        )
        assertEquals(20, trashed.trashDaysRemaining(now))
    }

    @Test
    fun normalizeLemmaTreatsCaseAndSpacingAsSameWord() {
        assertEquals("serendipity", normalizeLemma("  Serendipity "))
        val existing = newLocalWord("Serendipity", "", "机缘巧合", "")
        val duplicate = listOf(existing).findDuplicateWord("serendipity")
        assertEquals(existing.clientId, duplicate?.clientId)
    }

    @Test
    fun normalizeLemmaMergesCommonInflectionsWithoutDamagingWords() {
        assertEquals("run", normalizeLemma("running"))
        assertEquals("run", normalizeLemma("ran"))
        assertEquals("study", normalizeLemma("studies"))
        assertEquals("study", normalizeLemma("studying"))
        assertEquals("study", normalizeLemma("studied"))
        assertEquals("make", normalizeLemma("making"))
        assertEquals("write", normalizeLemma("writing"))
        assertEquals("big", normalizeLemma("bigger"))
        assertEquals("movie", normalizeLemma("movies"))
        assertEquals("water", normalizeLemma("water"))
        assertEquals("news", normalizeLemma("news"))
        assertEquals("means", normalizeLemma("means"))
    }

    @Test
    fun clipboardWordUsesLemmaPhoneticAndChineseMeaning() {
        val draft = parseClipboardWord("serendipity /ˌserənˈdɪpəti/ 机缘巧合")
        assertEquals("serendipity", draft?.lemma)
        assertEquals("/ˌserənˈdɪpəti/", draft?.phonetic)
        assertEquals("机缘巧合", draft?.meaning)
    }

    @Test
    fun clipboardWordIgnoresUrlsAndSentences() {
        assertEquals(null, parseClipboardWord("https://example.com/word"))
        assertEquals(null, parseClipboardWord("We found the book by serendipity."))
        assertEquals("ephemeral", parseClipboardWord("ephemeral")?.lemma)
    }

    @Test
    fun clipboardWordIgnoresPathsAndFilenames() {
        assertEquals(
            null,
            parseClipboardWord(
                "local_user/data/手持式裂隙灯/质量分类/release-1.0.0/model_conversion/iter_40000.onnx",
            ),
        )
        assertEquals(null, parseClipboardWord("iter_40000.onnx"))
        assertEquals(null, parseClipboardWord("C:\\Users\\model.pth"))
        assertEquals(null, parseClipboardWord("file:///tmp/word.txt"))
        assertEquals("look forward to", parseClipboardWord("look forward to")?.lemma)
    }

    @Test
    fun todayReviewMixesDueWordsUnreadResourcesAndInboxIdeas() {
        val word = newLocalWord("ephemeral", "", "短暂的", "")
        val resource = newLocalResource("https://example.com/review", "待读", "")
        val idea = newLocalIdea("待整理灵感")
        val skippedWord = word.copy(clientId = "skipped-word", lastReviewAt = word.createdAt)
        val items = listOf(word, resource, idea, skippedWord).todayReviewItems()

        assertEquals(listOf(TYPE_WORD, TYPE_RESOURCE, TYPE_IDEA), items.map(Memo::type))
        assertEquals("inbox", idea.status)
        assertEquals(1, listOf(word, resource, idea, skippedWord).todayReviewCounts().wordCount)
    }

    @Test
    fun imageMimeTypeNormalizationMatchesBackendContract() {
        assertEquals("image/png", normalizeImageMimeType("image/png"))
        assertEquals("image/png", normalizeImageMimeType("IMAGE/PNG; charset=binary"))
        assertEquals("image/jpeg", normalizeImageMimeType("image/jpg"))
        assertEquals("image/webp", normalizeImageMimeType("image/webp"))
        assertEquals("image/gif", normalizeImageMimeType("image/gif"))
        assertEquals(null, normalizeImageMimeType("image/heic"))
        assertEquals(null, normalizeImageMimeType(""))
        assertEquals(null, normalizeImageMimeType(null))
    }

    @Test
    fun imageMimeTypeFromFileNameHandlesAlbumDisplayNames() {
        assertEquals("image/png", imageMimeTypeFromFileName("screenshot.PNG"))
        assertEquals("image/jpeg", imageMimeTypeFromFileName("DCIM/Camera/IMG_0001.jpeg"))
        assertEquals("image/webp", imageMimeTypeFromFileName("sticker.webp"))
        assertEquals(null, imageMimeTypeFromFileName("no-extension"))
        assertEquals(null, imageMimeTypeFromFileName("trailing."))
        assertEquals(null, imageMimeTypeFromFileName(null))
    }

    @Test
    fun imageFileExtensionFollowsNormalizedMimeType() {
        assertEquals("png", imageFileExtensionForMimeType("image/png"))
        assertEquals("jpg", imageFileExtensionForMimeType("image/jpg"))
        assertEquals(null, imageFileExtensionForMimeType("image/heic"))
    }

    @Test
    fun imageMemoTitleUsesFileNameWithoutExtension() {
        assertEquals(
            "IMG_20260101_120000",
            imageMemoTitleFromFileName("/storage/DCIM/IMG_20260101_120000.jpg"),
        )
        assertEquals(DEFAULT_IMAGE_MEMO_TITLE, imageMemoTitleFromFileName(null))
        assertEquals(DEFAULT_IMAGE_MEMO_TITLE, imageMemoTitleFromFileName("   "))
        assertEquals(200, imageMemoTitleFromFileName("${"图".repeat(300)}.png").length)
    }

    @Test
    fun audioFileExtensionFollowsContainer() {
        assertEquals("m4a", audioFileExtensionForMimeType("audio/mp4"))
        assertEquals("m4a", audioFileExtensionForMimeType("audio/x-m4a"))
        assertEquals("webm", audioFileExtensionForMimeType("audio/webm;codecs=opus"))
        assertEquals("mp3", audioFileExtensionForMimeType("audio/mpeg"))
        assertEquals(null, audioFileExtensionForMimeType("audio/aac"))
        assertEquals(null, audioFileExtensionForMimeType(null))
    }

    @Test
    fun audioDownloadFileNameUsesTitleContainerAndMeetingFallback() {
        val meeting = newLocalVoiceIdea("产品周会", "/tmp/voice.m4a", 2_500)
            .copy(tags = listOf("语音", "会议"), createdAt = "2026-10-20T10:00:00Z")
        assertEquals("产品周会-2026-10-20.m4a", audioDownloadFileName(meeting))

        val untitledMeeting = meeting.copy(title = "")
        assertEquals("会议录音-2026-10-20.m4a", audioDownloadFileName(untitledMeeting))

        val unsafeTitle = meeting.copy(title = "周会/录音:第一段?")
        assertEquals("周会_录音_第一段_-2026-10-20.m4a", audioDownloadFileName(unsafeTitle))
    }

    @Test
    fun imageMetadataLabelsAreHumanReadable() {
        assertEquals("320 × 180 像素", imageDimensionsLabel(320, 180))
        assertEquals(null, imageDimensionsLabel(null, 180))
        assertEquals(null, imageDimensionsLabel(0, 180))
        assertEquals("512 B", formatFileSize(512))
        assertEquals("1.5 KB", formatFileSize(1536))
        assertEquals("2.0 MB", formatFileSize(2 * 1024 * 1024))
        assertEquals(null, formatFileSize(null))
        assertEquals(null, formatFileSize(-1))
    }

    @Test
    fun localImageMemoKeepsUploadDraft() {
        val memo = newLocalImage(
            title = "",
            body = "  旅行照片  ",
            mimeType = "image/png",
            sizeBytes = 2048,
        )
        assertEquals(TYPE_IMAGE, memo.type)
        assertEquals(DEFAULT_IMAGE_MEMO_TITLE, memo.title)
        assertEquals("旅行照片", memo.body)
        assertEquals("image/png", memo.imageMimeType)
        assertEquals(2048, memo.imageSizeBytes)
        assertEquals(SyncState.PENDING, memo.syncState)
        assertEquals(null, memo.id)
        assertEquals(true, memo.isImage())
        assertEquals(true, memo.hasUploadedImage())
    }

    @Test
    fun imageMemoWithoutUploadHasNoMetadata() {
        val memo = newLocalImage("相册图片", "", "image/jpeg", 1024)
            .copy(imageMimeType = null, imageSizeBytes = null)

        assertEquals(false, memo.hasUploadedImage())
        assertEquals(null, imageDimensionsLabel(memo.imageWidth, memo.imageHeight))
        assertEquals(null, formatFileSize(memo.imageSizeBytes))
    }

    @Test
    fun searchMatchesImageMemoByTitleAndBody() {
        val memo = newLocalImage("海边日落", "暑假旅行", "image/jpeg", 4096)
            .copy(imageWidth = 1920, imageHeight = 1080)

        assertEquals(true, memo.matchesQuery("日落"))
        assertEquals(true, memo.matchesQuery("旅行"))
        assertEquals(false, memo.matchesQuery("PPT"))
    }

    @Test
    fun searchMatchesImageOcrTextAndAutoTags() {
        val memo = newLocalImage("海边日落", "暑假旅行", "image/jpeg", 4096).copy(
            imageOcrText = "登机口 A12 登机时间 18:40",
            imageAutoTags = listOf("机票", "行程"),
            imageOcrStatus = "ready",
            imageOcrSource = "llm",
            imageOcrUpdatedAt = "2026-03-05T02:00:00Z",
        )

        // 标题与备注保持可搜索。
        assertEquals(true, memo.matchesQuery("日落"))
        assertEquals(true, memo.matchesQuery("旅行"))
        // 服务端 OCR 文字与自动标签同样进入本地缓存搜索。
        assertEquals(true, memo.matchesQuery("登机口"))
        assertEquals(true, memo.matchesQuery("机票"))
        assertEquals(false, memo.matchesQuery("护照"))
    }

    @Test
    fun imageOcrLabelsFollowBackendContract() {
        val memo = newLocalImage("截图", "", "image/png", 1024)

        assertEquals("未识别", memo.imageOcrStatusLabel())
        assertEquals("排队中", memo.copy(imageOcrStatus = "pending").imageOcrStatusLabel())
        assertEquals("识别中", memo.copy(imageOcrStatus = "processing").imageOcrStatusLabel())
        assertEquals("已识别", memo.copy(imageOcrStatus = "ready").imageOcrStatusLabel())
        assertEquals("识别失败", memo.copy(imageOcrStatus = "failed").imageOcrStatusLabel())
        assertEquals("未启用", memo.copy(imageOcrStatus = "disabled").imageOcrStatusLabel())
        assertEquals("未识别", memo.copy(imageOcrStatus = "unknown").imageOcrStatusLabel())

        assertEquals(null, memo.imageOcrSourceLabel())
        assertEquals("本地识别", memo.copy(imageOcrSource = "local").imageOcrSourceLabel())
        assertEquals("AI 识别", memo.copy(imageOcrSource = "llm").imageOcrSourceLabel())
        assertEquals(null, memo.copy(imageOcrSource = "other").imageOcrSourceLabel())
    }

    @Test
    fun imageMemoWithoutOcrMetadataHasNoRecognizedContent() {
        val memo = newLocalImage("相册图片", "", "image/jpeg", 1024)

        assertEquals(null, memo.imageOcrText)
        assertEquals("none", memo.imageOcrStatus)
        assertEquals(null, memo.imageOcrError)
        assertEquals(null, memo.imageOcrSource)
        assertEquals(emptyList<String>(), memo.imageAutoTags)
        assertEquals(null, memo.imageOcrUpdatedAt)
        assertEquals("未识别", memo.imageOcrStatusLabel())
        assertEquals(null, memo.imageOcrSourceLabel())
        assertEquals(false, memo.matchesQuery("识别"))
        assertEquals(true, memo.matchesQuery("相册"))
    }

    @Test
    fun compressionIsOnlyNeededOutsideServerLimits() {
        val twentyMb = 20L * 1024L * 1024L
        assertEquals(false, ImageCompressionPolicy.needsCompression(twentyMb, 4000, 3000))
        assertEquals(true, ImageCompressionPolicy.needsCompression(twentyMb + 1, 4000, 3000))
        assertEquals(true, ImageCompressionPolicy.needsCompression(1024, 12_001, 100))
        assertEquals(true, ImageCompressionPolicy.needsCompression(1024, 100, 12_001))
        assertEquals(false, ImageCompressionPolicy.needsCompression(1024, 12_000, 100))
        assertEquals(false, ImageCompressionPolicy.needsCompression(1024, 10_000, 5_000))
        assertEquals(true, ImageCompressionPolicy.needsCompression(1024, 10_000, 5_001))
        // 尺寸未知时只按字节数判断，避免因为读不到尺寸就误判为需要压缩。
        assertEquals(false, ImageCompressionPolicy.needsCompression(1024, 0, 0))
        assertEquals(true, ImageCompressionPolicy.needsCompression(twentyMb + 1, 0, 0))
    }

    @Test
    fun targetSizeKeepsImagesWithinLimitsWithoutUpscaling() {
        assertEquals(800 to 600, ImageCompressionPolicy.targetSize(800, 600))
        assertEquals(12_000 to 3_000, ImageCompressionPolicy.targetSize(24_000, 6_000))
        assertEquals(5_000 to 10_000, ImageCompressionPolicy.targetSize(20_000, 40_000))
        listOf(
            30_000 to 30_000,
            12_001 to 12_000,
            50_000 to 1_000,
            12_000 to 12_000,
        ).forEach { (width, height) ->
            val (targetWidth, targetHeight) = ImageCompressionPolicy.targetSize(width, height)
            assertEquals(true, targetWidth in 1..12_000)
            assertEquals(true, targetHeight in 1..12_000)
            assertEquals(
                true,
                targetWidth.toLong() * targetHeight.toLong() <= 50_000_000L,
            )
            assertEquals(true, targetWidth <= width)
            assertEquals(true, targetHeight <= height)
        }
    }

    @Test
    fun targetSizeNeverReturnsZero() {
        assertEquals(1 to 1, ImageCompressionPolicy.targetSize(0, 0))
        assertEquals(1 to 10, ImageCompressionPolicy.targetSize(-5, 10))
        assertEquals(1 to 12_000, ImageCompressionPolicy.targetSize(1, 100_000))
    }

    @Test
    fun shrinkSizeKeepsAspectRatioAndNeverReturnsZero() {
        assertEquals(700 to 350, ImageCompressionPolicy.shrinkSize(1_000, 500))
        assertEquals(1 to 1, ImageCompressionPolicy.shrinkSize(1, 1))
    }

    @Test
    fun sampleSizeUsesPowersOfTwoAndNeverUpscales() {
        assertEquals(1, ImageCompressionPolicy.sampleSizeFor(4_000, 3_000, 4_000, 3_000))
        assertEquals(2, ImageCompressionPolicy.sampleSizeFor(8_000, 6_000, 4_000, 3_000))
        assertEquals(2, ImageCompressionPolicy.sampleSizeFor(8_001, 6_000, 4_000, 3_000))
        assertEquals(4, ImageCompressionPolicy.sampleSizeFor(40_000, 30_000, 10_000, 7_000))
        assertEquals(1, ImageCompressionPolicy.sampleSizeFor(0, 0, 100, 100))
        assertEquals(1, ImageCompressionPolicy.sampleSizeFor(4_000, 3_000, 0, 0))
        val powersOfTwo = setOf(1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
        listOf(
            ImageCompressionPolicy.sampleSizeFor(12_000, 12_000, 7_071, 7_071),
            ImageCompressionPolicy.sampleSizeFor(100_000, 50, 12_000, 6),
            ImageCompressionPolicy.sampleSizeFor(3_000, 4_000, 1_000, 1_333),
        ).forEach { sampleSize ->
            assertEquals(true, sampleSize in powersOfTwo)
        }
    }

    @Test
    fun outputFormatFollowsAlphaChannel() {
        assertEquals(
            ImageOutputFormat.PNG,
            ImageCompressionPolicy.chooseOutputFormat(hasAlpha = true, sourceMimeType = "image/png"),
        )
        assertEquals(
            ImageOutputFormat.JPEG,
            ImageCompressionPolicy.chooseOutputFormat(hasAlpha = false, sourceMimeType = "image/png"),
        )
        assertEquals(
            ImageOutputFormat.JPEG,
            ImageCompressionPolicy.chooseOutputFormat(hasAlpha = false, sourceMimeType = "image/gif"),
        )
        assertEquals(
            ImageOutputFormat.JPEG,
            ImageCompressionPolicy.chooseOutputFormat(hasAlpha = false, sourceMimeType = null),
        )
        assertEquals(
            ImageOutputFormat.PNG,
            ImageCompressionPolicy.chooseOutputFormat(hasAlpha = true, sourceMimeType = "image/webp"),
        )
        assertEquals("image/jpeg", ImageOutputFormat.JPEG.mimeType)
        assertEquals("image/png", ImageOutputFormat.PNG.mimeType)
    }

    @Test
    fun formatLabelFollowsNormalizedMimeType() {
        assertEquals("PNG", ImageCompressionPolicy.formatLabel("image/png"))
        assertEquals("JPEG", ImageCompressionPolicy.formatLabel("image/jpg"))
        assertEquals("WebP", ImageCompressionPolicy.formatLabel("image/webp"))
        assertEquals("GIF", ImageCompressionPolicy.formatLabel("image/gif"))
        assertEquals("图片", ImageCompressionPolicy.formatLabel("image/heic"))
        assertEquals("图片", ImageCompressionPolicy.formatLabel(null))
    }

    @Test
    fun compressionReminderListsSizeDimensionAndFormatChanges() {
        val text = ImageCompressionPolicy.describeCompression(
            originalByteCount = 25 * 1024 * 1024,
            newByteCount = 2 * 1024 * 1024,
            originalWidth = 14_400,
            originalHeight = 9_000,
            newWidth = 12_000,
            newHeight = 7_500,
            sourceMimeType = "image/png",
            outputFormat = ImageOutputFormat.JPEG,
            animationDropped = false,
        )

        assertEquals(
            "图片已自动压缩后收藏：25.0 MB → 2.0 MB；" +
                "尺寸 14400 × 9000 → 12000 × 7500；格式 PNG → JPEG",
            text,
        )
    }

    @Test
    fun compressionReminderOmitsUnchangedDetailsAndNotesDroppedGifAnimation() {
        val onlySize = ImageCompressionPolicy.describeCompression(
            originalByteCount = 21 * 1024 * 1024,
            newByteCount = 3 * 1024 * 1024,
            originalWidth = 4_000,
            originalHeight = 3_000,
            newWidth = 4_000,
            newHeight = 3_000,
            sourceMimeType = "image/jpeg",
            outputFormat = ImageOutputFormat.JPEG,
            animationDropped = false,
        )
        assertEquals("图片已自动压缩后收藏：21.0 MB → 3.0 MB", onlySize)

        val gif = ImageCompressionPolicy.describeCompression(
            originalByteCount = 30 * 1024 * 1024,
            newByteCount = 1024 * 1024,
            originalWidth = 20_000,
            originalHeight = 20_000,
            newWidth = 5_000,
            newHeight = 5_000,
            sourceMimeType = "image/gif",
            outputFormat = ImageOutputFormat.JPEG,
            animationDropped = true,
        )
        assertEquals(
            "图片已自动压缩后收藏：30.0 MB → 1.0 MB；" +
                "尺寸 20000 × 20000 → 5000 × 5000；格式 GIF → JPEG；" +
                "动图已转为静态图，仅保留第一帧",
            gif,
        )
    }
}
