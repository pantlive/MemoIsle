package com.memoisle.app.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidReleaseTest {
    private val sha = "a".repeat(64)

    private fun releaseJson(): JSONObject = JSONObject()
        .put("version_code", 6)
        .put("version_name", "0.1.5")
        .put("sha256", sha)
        .put("size", 25_000_000L)
        .put("release_notes", "支持自动更新")
        .put("download_url", "android/download")

    private fun release(versionCode: Int) = AndroidRelease(
        versionCode = versionCode,
        versionName = "0.1.$versionCode",
        sha256 = sha,
        size = 1,
        releaseNotes = "",
        downloadUrl = "android/download",
    )

    @Test
    fun parsesServerResponse() {
        val release = AndroidRelease.fromJson(releaseJson())
        assertNotNull(release)
        release!!
        assertEquals(6, release.versionCode)
        assertEquals("0.1.5", release.versionName)
        assertEquals(sha, release.sha256)
        assertEquals(25_000_000L, release.size)
        assertEquals("支持自动更新", release.releaseNotes)
        assertEquals("android/download", release.downloadUrl)
    }

    @Test
    fun optionalFieldsFallBack() {
        val json = releaseJson().apply {
            remove("release_notes")
            remove("download_url")
            put("sha256", "A".repeat(64))
        }
        val release = AndroidRelease.fromJson(json)!!
        assertEquals("", release.releaseNotes)
        assertEquals("android/download", release.downloadUrl)
        assertEquals(sha, release.sha256)
    }

    @Test
    fun missingOrInvalidFieldsReturnNull() {
        for (field in listOf("version_code", "version_name", "sha256", "size")) {
            assertNull(field, AndroidRelease.fromJson(releaseJson().apply { remove(field) }))
        }
        assertNull(AndroidRelease.fromJson(releaseJson().put("version_code", "6")))
        assertNull(AndroidRelease.fromJson(releaseJson().put("version_code", true)))
        assertNull(AndroidRelease.fromJson(releaseJson().put("version_code", 0)))
        assertNull(AndroidRelease.fromJson(releaseJson().put("version_code", 6.5)))
        assertNull(AndroidRelease.fromJson(releaseJson().put("version_name", "  ")))
        assertNull(AndroidRelease.fromJson(releaseJson().put("sha256", "abc")))
        assertNull(AndroidRelease.fromJson(releaseJson().put("size", 0)))
        assertNull(AndroidRelease.fromJson(JSONObject()))
    }

    @Test
    fun comparesVersionCode() {
        assertTrue(isNewerRelease(release(6), currentVersionCode = 5))
        assertFalse(isNewerRelease(release(5), currentVersionCode = 5))
        assertFalse(isNewerRelease(release(4), currentVersionCode = 5))
    }

    @Test
    fun ignoredVersionOnlySkipsAutomaticChecks() {
        assertFalse(shouldPromptRelease(release(6), 5, ignoredVersionCode = 6, manual = false))
        assertTrue(shouldPromptRelease(release(6), 5, ignoredVersionCode = 6, manual = true))
        assertTrue(shouldPromptRelease(release(7), 5, ignoredVersionCode = 6, manual = false))
        assertTrue(shouldPromptRelease(release(6), 5, ignoredVersionCode = null, manual = false))
        assertFalse(shouldPromptRelease(release(5), 5, ignoredVersionCode = null, manual = true))
    }

    @Test
    fun autoCheckAtMostOncePerDay() {
        val now = 10L * UPDATE_AUTO_CHECK_INTERVAL_MS
        assertTrue(shouldAutoCheck(lastCheckedAtMs = 0, nowMs = now))
        assertFalse(shouldAutoCheck(lastCheckedAtMs = now - 1_000, nowMs = now))
        assertTrue(shouldAutoCheck(lastCheckedAtMs = now - UPDATE_AUTO_CHECK_INTERVAL_MS, nowMs = now))
        // 系统时间被往回调时不要一直卡住不检查。
        assertTrue(shouldAutoCheck(lastCheckedAtMs = now + 1_000, nowMs = now))
    }

    @Test
    fun cleanupKeepsOnlyNewerVerifiedPackages() {
        assertEquals("memoisle-6.apk", updateApkFileName(6))
        assertEquals(6, updateApkVersionCode("memoisle-6.apk"))
        assertNull(updateApkVersionCode("memoisle-6.apk.part"))
        assertFalse(isStaleUpdateFile("memoisle-6.apk", currentVersionCode = 5))
        assertTrue(isStaleUpdateFile("memoisle-5.apk", currentVersionCode = 5))
        assertTrue(isStaleUpdateFile("memoisle-6.apk.part", currentVersionCode = 5))
        assertTrue(isStaleUpdateFile("other.txt", currentVersionCode = 5))
    }
}
