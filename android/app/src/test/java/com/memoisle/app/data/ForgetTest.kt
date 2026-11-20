package com.memoisle.app.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ForgetTest {
    @Test
    fun itemJsonRoundTripKeepsTextPinAndAttachments() {
        val item = ForgetItem(
            id = "11111111-1111-4111-8111-111111111111",
            title = "钥匙",
            content = "在抽屉里",
            pinned = true,
            version = 2,
            createdAt = "2026-11-20T00:00:00Z",
            updatedAt = "2026-11-20T01:00:00Z",
            attachments = listOf(
                ForgetAttachment(
                    id = "22222222-2222-4222-8222-222222222222",
                    kind = "file",
                    originalName = "备忘.txt",
                    mime = "text/plain",
                    size = 12,
                    sha256 = "abc",
                    position = 0,
                    createdAt = "2026-11-20T01:00:00Z",
                ),
            ),
        )
        assertEquals(item, ForgetItem.fromJson(JSONObject(item.toJson().toString())))
    }

    @Test
    fun missingAttachmentsBecomeAnEmptyList() {
        val json = JSONObject(
            """
            {"id":"33333333-3333-4333-8333-333333333333","title":"","content":"",
             "pinned":false,"version":1,"created_at":"2026-11-20T00:00:00Z",
             "updated_at":"2026-11-20T00:00:00Z"}
            """.trimIndent(),
        )
        val item = ForgetItem.fromJson(json)
        assertTrue(item.attachments.isEmpty())
        assertEquals("", item.title)
    }

    @Test
    fun textLimitsMatchWebAndEmptyTextIsAllowed() {
        assertNull(forgetTextError("", ""))
        assertNull(forgetTextError("  标题  ", "正文"))
        assertNull(forgetTextError("标".repeat(FORGET_TITLE_MAX), ""))
        assertEquals("标题最多 100 个字", forgetTextError("标".repeat(FORGET_TITLE_MAX + 1), ""))
        assertEquals("正文最多 10000 个字", forgetTextError("", "文".repeat(FORGET_CONTENT_MAX + 1)))
        assertEquals(1, forgetTextLength("😀"))
    }

    @Test
    fun fileSizeDisplayNameAndSaveType() {
        assertNull(forgetFileError(1))
        assertNull(forgetFileError(FORGET_MAX_ATTACHMENT_BYTES))
        assertNull(forgetFileError(null))
        assertEquals("附件内容不能为空", forgetFileError(0))
        assertEquals("附件不能超过 20 MB", forgetFileError(FORGET_MAX_ATTACHMENT_BYTES + 1))
        assertEquals("未命名", forgetDisplayTitle("  "))
        assertEquals("钥匙", forgetDisplayTitle(" 钥匙 "))
        assertEquals("12 B", formatForgetBytes(12))
        assertEquals("2 KB", formatForgetBytes(2048))
        assertEquals("1.5 MB", formatForgetBytes((1.5 * 1024 * 1024).toLong()))
        assertEquals("备忘.txt", forgetSaveName("文件夹/备忘.txt"))
        assertEquals("file", forgetSaveName("   "))
        val image = sampleAttachment(kind = "image", mime = "image/png", name = "图.png")
        val html = sampleAttachment(kind = "file", mime = "text/html", name = "页面.html")
        val fake = sampleAttachment(kind = "file", mime = "image/png", name = "伪装.png")
        assertTrue(isForgetImage(image))
        assertEquals("image/png", forgetSaveType(image))
        assertEquals("application/octet-stream", forgetSaveType(html))
        assertEquals("application/octet-stream", forgetSaveType(fake))
    }

    private fun sampleAttachment(kind: String, mime: String, name: String) = ForgetAttachment(
        id = "44444444-4444-4444-8444-444444444444",
        kind = kind,
        originalName = name,
        mime = mime,
        size = 4,
        sha256 = "abc",
        position = 0,
        createdAt = "2026-11-20T00:00:00Z",
    )
}
