package com.memoisle.app.data

import com.memoisle.app.TestStrings.zh
import java.util.Calendar
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RelayTest {
    @Test
    fun parsesTextItem() {
        val item = RelayItem.fromJson(
            JSONObject(
                """
                {"id":"t1","kind":"text","source":"web","target":"android",
                 "filename":null,"mime_type":null,"size":12,
                 "created_at":"2026-11-19T08:00:00Z","expires_at":"2026-11-19T08:10:00Z",
                 "expires_in":598,"text":"你好 hello"}
                """.trimIndent(),
            ),
        )
        assertTrue(item.isText)
        assertEquals("t1", item.id)
        assertEquals("web", item.source)
        assertEquals("你好 hello", item.text)
        assertNull(item.filename)
        assertNull(item.mimeType)
        assertEquals(598, item.expiresIn)
    }

    @Test
    fun parsesFileItemWithoutText() {
        val item = RelayItem.fromJson(
            JSONObject()
                .put("id", "f1").put("kind", "file").put("source", "web").put("target", "android")
                .put("filename", "报告.pdf").put("mime_type", "application/pdf")
                .put("size", 21_000_000L).put("created_at", "2026-11-19T08:00:00Z")
                .put("expires_at", "2026-11-19T08:10:00Z").put("expires_in", -3)
                .put("text", JSONObject.NULL),
        )
        assertFalse(item.isText)
        assertFalse(item.isImage)
        assertEquals("报告.pdf", item.filename)
        assertEquals("application/pdf", item.mimeType)
        assertEquals(21_000_000L, item.size)
        assertEquals(0, item.expiresIn)
        assertNull(item.text)
    }

    @Test
    fun limitsMatchServer() {
        assertEquals("请输入要发送的内容。", zh(relayTextError("   ")))
        assertNull(relayTextError("字".repeat(34_133)))
        assertTrue(zh(relayTextError("字".repeat(34_134)))!!.contains("100 KB"))
        assertNull(relayFileError("a.bin", null))
        assertNull(relayFileError("a.bin", RELAY_MAX_FILE_BYTES))
        assertTrue(zh(relayFileError("大.zip", RELAY_MAX_FILE_BYTES + 1))!!.contains("20 MB"))
        assertTrue(zh(relayFileError("空.txt", 0))!!.contains("空文件"))
    }

    @Test
    fun formatsSizeAndRemaining() {
        assertEquals("512 B", formatRelayBytes(512))
        assertEquals("1.5 KB", formatRelayBytes(1536))
        assertEquals("5.0 MB", formatRelayBytes(5L * 1024 * 1024))
        assertEquals("10:00", zh(formatRelayRemaining(600)))
        assertEquals("1:01", zh(formatRelayRemaining(61)))
        assertEquals("已过期", zh(formatRelayRemaining(0)))
        assertEquals("Expired", com.memoisle.app.TestStrings.en(formatRelayRemaining(0)))
        assertEquals("手机", zh(relayDeviceLabel(RELAY_DEVICE_ANDROID)))
        assertEquals("网页", zh(relayDeviceLabel(RELAY_DEVICE_WEB)))
    }

    @Test
    fun detectsImageItemsAndClipboardNames() {
        val image = RelayItem.fromJson(
            JSONObject()
                .put("id", "i1").put("kind", "file").put("source", "web").put("target", "android")
                .put("filename", "shot.jpg").put("mime_type", "image/jpeg")
                .put("size", 1200L).put("created_at", "2026-11-20T08:00:00Z")
                .put("expires_at", "2026-11-20T08:10:00Z").put("expires_in", 600)
                .put("text", JSONObject.NULL),
        )
        assertTrue(image.isImage)
        assertFalse(image.isText)

        val text = RelayItem.fromJson(
            JSONObject()
                .put("id", "t1").put("kind", "text").put("source", "web").put("target", "android")
                .put("filename", JSONObject.NULL).put("mime_type", "image/png")
                .put("size", 4L).put("created_at", "2026-11-20T08:00:00Z")
                .put("expires_at", "2026-11-20T08:10:00Z").put("expires_in", 600)
                .put("text", "hi"),
        )
        assertFalse(text.isImage)

        assertEquals("png", relayImageExtension("image/png"))
        assertEquals("jpg", relayImageExtension("image/jpeg"))
        assertEquals("jpg", relayImageExtension("image/jpg"))
        assertEquals("gif", relayImageExtension("IMAGE/GIF"))
        assertEquals("webp", relayImageExtension("image/webp; charset=binary"))
        assertEquals("png", relayImageExtension(null))
        assertEquals("png", relayImageExtension("application/pdf"))

        val calendar = Calendar.getInstance()
        calendar.clear()
        calendar.set(2026, Calendar.NOVEMBER, 20, 15, 30, 0)
        assertEquals(
            "clipboard-20261120-153000.png",
            relayClipboardImageName("image/png", calendar.timeInMillis),
        )
        assertEquals(
            "clipboard-20261120-153000.jpg",
            relayClipboardImageName("image/jpeg", calendar.timeInMillis),
        )
    }
}
