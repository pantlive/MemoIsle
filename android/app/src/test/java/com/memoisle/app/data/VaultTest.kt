package com.memoisle.app.data

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class VaultTest {
    // 由 Python cryptography 独立生成，等同于浏览器端写入的密文。
    private val material = VaultKeyMaterial(
        kdf = VaultCrypto.KDF,
        iterations = 600_000,
        salt = "GDsQ/b4QUgVcsRdrNZI4mg==",
        wrappedKey = "S3wrU8zCCdu4iVRdasTmgqbUlqA0k79AlNo/CzrgPBlvCaqfoER2Y72VdwM8nuDX",
        wrapIv = "qGdwbn8bdmswe/im",
    )
    private val itemId = "7d1c5a52-3d3b-4c1e-9a43-2f1b8c0e5d11"
    private val itemIv = "imgpv+4FnMN2TiYB"
    private val itemCiphertext = "55LI2hkSOqGyrulYRfHuKm86JSlkLeZfIKVzDKMcqLaCOazwF4brZDhh38CyYJqrbLNWJ5VHW7pDdom5DFGy9T/ChXLEVX/jKuaznTOKT/a51LkLLF9UhqXwYLqmFVtWHJHz9bEq//bEkU2Ja4ujrsx3SBBwnpFMqwWs4WnZYHhoXrI619Tx9AcC65L4NEvVRrjBBOaeTiDHxQdBlFhoiUeCBSzzNHIBOJ8cLYcRB46fh7D92prEVriZ/qBzWkaMAb76O6gLGi3Xk7CSJahCb8+FE3OUHJ+9Qob+ZTR3GVaDtw4lJaKSCB3M5vYDlC3ozV7EiGVViNotr23wRF8uRJk="

    @Test
    fun decryptsItemsWrittenByWeb() {
        // 主密码用分解形式的 é 输入，NFC 规范化后应和浏览器派生出同一把密钥。
        val key = VaultCrypto.unlock("café 主密码 test", material)
        val data = VaultItemData.fromJson(
            VaultCrypto.decryptItem(key, itemId, itemIv, itemCiphertext).toString(Charsets.UTF_8),
        )
        assertEquals(VAULT_KIND_LOGIN, data.kind)
        assertEquals("GitHub", data.title)
        assertEquals("octocat", data.username)
        assertEquals("pa55-word-xyz", data.password)
        assertEquals("备注", data.notes)
        assertEquals(90, data.rotateDays)
        assertEquals("2026-03-30T08:00:00.000Z", data.changedAt)
    }

    @Test
    fun wrongPasswordIsRejected() {
        try {
            VaultCrypto.unlock("wrong password", material)
            fail("应拒绝错误的主密码")
        } catch (error: WrongMasterPasswordException) {
            assertEquals("主密码不正确。", error.message)
        }
    }

    @Test
    fun itemCiphertextIsBoundToItemId() {
        val key = VaultCrypto.unlock("café 主密码 test", material)
        val (iv, ciphertext) = VaultCrypto.encryptItem(key, "item-a", "{\"kind\":\"secret\"}".toByteArray())
        assertEquals(
            "{\"kind\":\"secret\"}",
            VaultCrypto.decryptItem(key, "item-a", iv, ciphertext).toString(Charsets.UTF_8),
        )
        try {
            VaultCrypto.decryptItem(key, "item-b", iv, ciphertext)
            fail("换了条目 ID 不应解密成功")
        } catch (error: VaultDecryptException) {
            // 预期：附加认证数据不一致。
        }
    }

    @Test
    fun jsonRoundTripKeepsKindFields() {
        val recovery = VaultItemData(
            kind = VAULT_KIND_RECOVERY,
            title = "GitHub 2FA",
            account = "me@example.com",
            codes = parseRecoveryCodes("aaa-111 bbb-222,ccc-333\naaa-111"),
        )
        val parsed = VaultItemData.fromJson(recovery.toJson())
        assertEquals(listOf("aaa-111", "bbb-222", "ccc-333"), parsed.codes.map { it.code })
        assertEquals("me@example.com", parsed.account)
        val legacy = VaultItemData.fromJson("{\"kind\":\"secret\",\"title\":\"\",\"secret\":\"sk\",\"rotateDays\":7}")
        assertEquals("未命名", legacy.title)
        assertEquals(0, legacy.rotateDays)
    }

    @Test
    fun secretChangeStampsTime() {
        val now = Instant.parse("2026-10-16T00:00:00Z")
        val before = VaultItemData(kind = VAULT_KIND_LOGIN, title = "a", password = "old")
        assertEquals(now.toString(), stampSecretChange(before, before.copy(password = "new"), now).changedAt)
        assertEquals("", stampSecretChange(before, before.copy(notes = "x"), now).changedAt)
        assertEquals("", stampSecretChange(null, VaultItemData(kind = VAULT_KIND_SECRET), now).changedAt)
        // 纳秒精度截到毫秒，网页端 Date.parse 才能稳定解析。
        val precise = Instant.parse("2026-10-16T14:16:41.373547622Z")
        assertEquals(
            "2026-10-16T14:16:41.373Z",
            stampSecretChange(before, before.copy(password = "new"), precise).changedAt,
        )
    }

    @Test
    fun generatedPasswordsAreStrong() {
        repeat(20) {
            val password = generateVaultPassword()
            assertEquals(20, password.length)
            assertFalse(isWeakVaultPassword(password))
        }
        assertTrue(isWeakVaultPassword("abc123"))
        assertTrue(isWeakVaultPassword("password12"))
        assertFalse(isWeakVaultPassword(""))
    }

    @Test
    fun remindersMatchWebRules() {
        val today = LocalDate.of(2026, 10, 16)
        fun entry(id: String, data: VaultItemData, created: String = "2026-10-10T00:00:00Z") =
            VaultEntry(id, 1, created, data)
        val entries = listOf(
            entry("old", VaultItemData(VAULT_KIND_LOGIN, "老账号", password = "Str0ng!Pass-word-xyz", rotateDays = 90, changedAt = "2026-03-30T00:00:00Z")),
            entry("soon", VaultItemData(VAULT_KIND_LOGIN, "快到期", password = "An0ther!Strong-one-q", rotateDays = 30, changedAt = "2026-09-21T00:00:00Z")),
            entry("weak", VaultItemData(VAULT_KIND_LOGIN, "弱密码", password = "abc123")),
            entry("pin", VaultItemData(VAULT_KIND_LOGIN, "门禁", password = "1234", skipChecks = true)),
            entry("r1", VaultItemData(VAULT_KIND_LOGIN, "重复甲", password = "Shared#Passw0rd-777")),
            entry("r2", VaultItemData(VAULT_KIND_LOGIN, "重复乙", password = "Shared#Passw0rd-777")),
            entry("expired", VaultItemData(VAULT_KIND_SECRET, "过期密钥", secret = "sk", expiresOn = "2026-10-13")),
            entry("expiring", VaultItemData(VAULT_KIND_SECRET, "将到期", secret = "sk2", expiresOn = "2026-10-26")),
            entry("far", VaultItemData(VAULT_KIND_SECRET, "远期", secret = "sk3", expiresOn = "2026-12-15")),
            entry("empty", VaultItemData(VAULT_KIND_SECRET, "没填", expiresOn = "2026-10-01")),
            entry("low", VaultItemData(VAULT_KIND_RECOVERY, "恢复码少", codes = listOf(RecoveryCode("a", true), RecoveryCode("b", false)))),
            entry("none", VaultItemData(VAULT_KIND_RECOVERY, "恢复码空", codes = listOf(RecoveryCode("c", true)))),
        )
        val reminders = collectVaultReminders(entries, today, ZoneOffset.UTC)
        val byEntry = reminders.groupBy({ it.entryId }, { it.type })
        assertEquals(listOf(VaultReminderType.ROTATE), byEntry["old"])
        assertEquals(listOf(VaultReminderType.ROTATE_SOON), byEntry["soon"])
        assertEquals(listOf(VaultReminderType.WEAK), byEntry["weak"])
        assertEquals(listOf(VaultReminderType.REUSED), byEntry["r1"])
        assertEquals(listOf(VaultReminderType.EXPIRED), byEntry["expired"])
        assertEquals(listOf(VaultReminderType.EXPIRING), byEntry["expiring"])
        assertEquals(listOf(VaultReminderType.CODES_LOW), byEntry["low"])
        assertEquals(listOf(VaultReminderType.CODES_EMPTY), byEntry["none"])
        assertFalse(byEntry.containsKey("pin"))
        assertFalse(byEntry.containsKey("far"))
        assertFalse(byEntry.containsKey("empty"))
        assertTrue(reminders.takeWhile { it.danger }.size == reminders.count { it.danger })
        assertEquals("已 200 天没有更换，设定为每 90 天换一次。", reminders.first { it.entryId == "old" }.message)
        assertEquals("和「重复乙」用的是同一个密码。", reminders.first { it.entryId == "r1" }.message)
    }
}
