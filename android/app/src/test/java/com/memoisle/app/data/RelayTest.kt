package com.memoisle.app.data

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
        assertEquals("报告.pdf", item.filename)
        assertEquals("application/pdf", item.mimeType)
        assertEquals(21_000_000L, item.size)
        assertEquals(0, item.expiresIn)
        assertNull(item.text)
    }

    @Test
    fun limitsMatchServer() {
        assertEquals("请输入要发送的内容。", relayTextError("   "))
        assertNull(relayTextError("字".repeat(34_133)))
        assertTrue(relayTextError("字".repeat(34_134))!!.contains("100 KB"))
        assertNull(relayFileError("a.bin", null))
        assertNull(relayFileError("a.bin", RELAY_MAX_FILE_BYTES))
        assertTrue(relayFileError("大.zip", RELAY_MAX_FILE_BYTES + 1)!!.contains("20 MB"))
        assertTrue(relayFileError("空.txt", 0)!!.contains("空文件"))
    }

    @Test
    fun formatsSizeAndRemaining() {
        assertEquals("512 B", formatRelayBytes(512))
        assertEquals("1.5 KB", formatRelayBytes(1536))
        assertEquals("5.0 MB", formatRelayBytes(5L * 1024 * 1024))
        assertEquals("10:00", formatRelayRemaining(600))
        assertEquals("1:01", formatRelayRemaining(61))
        assertEquals("已过期", formatRelayRemaining(0))
        assertEquals("手机", relayDeviceLabel(RELAY_DEVICE_ANDROID))
        assertEquals("网页", relayDeviceLabel(RELAY_DEVICE_WEB))
    }
}
