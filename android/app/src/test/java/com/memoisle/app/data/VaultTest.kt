package com.memoisle.app.data

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import org.json.JSONObject
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

    @Test
    fun subscriptionJsonRoundTripKeepsWebFields() {
        val original = VaultItemData(
            kind = VAULT_KIND_SUBSCRIPTION,
            title = "Claude Max",
            provider = "claude",
            plan = "Max",
            account = "me@example.com",
            startedOn = "2026-01-15",
            expiresOn = "2026-11-30",
            billingCycle = "yearly",
            price = "20.00",
            balance = "12.50",
            currency = "USD",
            notes = "备注",
        )
        val json = JSONObject(original.toJson())
        assertEquals(1, json.getInt("v"))
        assertEquals("subscription", json.getString("kind"))
        listOf(
            "title", "provider", "plan", "account",
            "startedOn", "expiresOn", "billingCycle", "price", "balance",
            "currency", "notes",
        ).forEach { key -> assertTrue("缺少字段 $key", json.has(key)) }
        assertFalse(json.has("username"))
        assertFalse(json.has("skipChecks"))
        assertFalse(json.has("secret"))
        assertFalse(json.has("codes"))
        assertFalse(json.has("host"))

        val parsed = VaultItemData.fromJson(original.toJson())
        assertEquals(original, parsed)

        val fromWeb = VaultItemData.fromJson(
            """
            {
              "v": 1,
              "kind": "subscription",
              "title": "Grok SuperGrok",
              "provider": "grok",
              "plan": "SuperGrok",
              "account": "user@x.com",
              "startedOn": "2026-03-01",
              "expiresOn": "2027-03-01",
              "billingCycle": "monthly",
              "price": "30",
              "balance": "0.00",
              "currency": "USD",
              "notes": "n"
            }
            """.trimIndent(),
        )
        assertEquals(VAULT_KIND_SUBSCRIPTION, fromWeb.kind)
        assertEquals("Grok SuperGrok", fromWeb.title)
        assertEquals("grok", fromWeb.provider)
        assertEquals("SuperGrok", fromWeb.plan)
        assertEquals("user@x.com", fromWeb.account)
        assertEquals("2026-03-01", fromWeb.startedOn)
        assertEquals("2027-03-01", fromWeb.expiresOn)
        assertEquals("monthly", fromWeb.billingCycle)
        assertEquals("30", fromWeb.price)
        assertEquals("0.00", fromWeb.balance)
        assertEquals("USD", fromWeb.currency)
        assertEquals("n", fromWeb.notes)
        val savedAgain = VaultItemData.fromJson(fromWeb.toJson())
        assertEquals(fromWeb, savedAgain)
    }

    @Test
    fun subscriptionJsonNormalizesInvalidFields() {
        val normalized = VaultItemData.fromJson(
            """
            {
              "kind": "subscription",
              "title": "",
              "provider": "unknown-ai",
              "plan": "X",
              "account": "a",
              "password": "p",
              "url": "https://x.com",
              "startedOn": "not-a-date",
              "expiresOn": "2026-13-40",
              "billingCycle": "weekly",
              "price": "12.345",
              "balance": "-5",
              "currency": "usd",
              "notes": "",
              "rotateDays": 7
            }
            """.trimIndent(),
        )
        assertEquals("未命名", normalized.title)
        assertEquals("other", normalized.provider)
        assertEquals("X", normalized.plan)
        assertEquals("", normalized.startedOn)
        assertEquals("", normalized.expiresOn)
        assertEquals("monthly", normalized.billingCycle)
        assertEquals("", normalized.price)
        assertEquals("", normalized.balance)
        assertEquals("USD", normalized.currency)
        assertEquals(0, normalized.rotateDays)

        val numbers = VaultItemData.fromJson(
            """{"kind":"subscription","price":"123456789.99","balance":"0.5","currency":"CNY","startedOn":"2026-02-28","billingCycle":"none","provider":"chatgpt"}""",
        )
        assertEquals("123456789.99", numbers.price)
        assertEquals("0.5", numbers.balance)
        assertEquals("CNY", numbers.currency)
        assertEquals("2026-02-28", numbers.startedOn)
        assertEquals("none", numbers.billingCycle)
        assertEquals("chatgpt", numbers.provider)

        val written = JSONObject(
            VaultItemData(
                kind = VAULT_KIND_SUBSCRIPTION,
                provider = "nope",
                billingCycle = "weekly",
                price = "12.345",
                balance = "-1",
                currency = "us",
                startedOn = "2026-02-30",
                expiresOn = "abcd",
            ).toJson(),
        )
        assertEquals("other", written.getString("provider"))
        assertEquals("monthly", written.getString("billingCycle"))
        assertEquals("", written.getString("price"))
        assertEquals("", written.getString("balance"))
        assertEquals("USD", written.getString("currency"))
        assertEquals("", written.getString("startedOn"))
        assertEquals("", written.getString("expiresOn"))

        assertEquals("Claude Max", defaultSubscriptionTitle("claude", "Max"))
        assertEquals("\$12.50", formatVaultMoney("USD", "12.50"))
        assertEquals("¥8", formatVaultMoney("CNY", "8"))
        assertEquals("EUR12.50", formatVaultMoney("EUR", "12.50"))
    }

    @Test
    fun subscriptionSerializationDropsLegacyPasswordAndUrlAfterEditing() {
        // 共用数据类即使带有旧字段，订阅写回时也只保存管理信息。
        val legacy = VaultItemData(
            kind = VAULT_KIND_SUBSCRIPTION,
            title = "Claude Max",
            account = "me@example.com",
            password = "abc123",
            url = "https://claude.ai",
            expiresOn = "2026-11-30",
        )
        val serialized = JSONObject(legacy.toJson())
        assertFalse(serialized.has("password"))
        assertFalse(serialized.has("url"))

        // 模拟解密旧版 JSON 后编辑备注，再次保存不能保留密码和网址。
        val oldJson = serialized.put("password", legacy.password).put("url", legacy.url)
            .put("rotateDays", 90).put("changedAt", "2026-03-30T00:00:00Z")
        val parsed = VaultItemData.fromJson(oldJson.toString())
        assertEquals("", parsed.password)
        assertEquals("", parsed.url)
        assertEquals("", parsed.secretValue)
        assertEquals(0, parsed.rotateDays)
        assertEquals("", parsed.changedAt)
        val edited = parsed.copy(notes = "已确认续费")
        val saved = JSONObject(edited.toJson())
        assertFalse(saved.has("password"))
        assertFalse(saved.has("url"))
        assertFalse(saved.has("rotateDays"))
        assertFalse(saved.has("changedAt"))
        assertEquals("已确认续费", saved.getString("notes"))
        assertEquals("me@example.com", saved.getString("account"))
        assertEquals("2026-11-30", saved.getString("expiresOn"))
    }

    @Test
    fun subscriptionIgnoresLegacyPasswordChecksAndRotation() {
        val now = Instant.parse("2026-10-16T00:00:00Z")
        val before = VaultItemData(kind = VAULT_KIND_SUBSCRIPTION, title = "Claude", password = "old")
        assertEquals("", stampSecretChange(before, before.copy(password = "new"), now).changedAt)
        assertEquals("", stampSecretChange(before, before.copy(notes = "x"), now).changedAt)

        val today = LocalDate.of(2026, 10, 16)
        fun entry(id: String, data: VaultItemData) = VaultEntry(id, 1, "2026-10-10T00:00:00Z", data)
        val entries = listOf(
            entry(
                "sub",
                VaultItemData(
                    VAULT_KIND_SUBSCRIPTION,
                    "Claude Max",
                    password = "abc123",
                    expiresOn = "2026-10-13",
                    rotateDays = 90,
                    changedAt = "2026-03-30T00:00:00Z",
                ),
            ),
            entry("login", VaultItemData(VAULT_KIND_LOGIN, "同密码", password = "abc123")),
        )
        val reminders = collectVaultReminders(entries, today, ZoneOffset.UTC)
        assertEquals(listOf(VaultReminderType.EXPIRED), reminders.filter { it.entryId == "sub" }.map { it.type })
        assertEquals(listOf(VaultReminderType.WEAK), reminders.filter { it.entryId == "login" }.map { it.type })
        assertEquals(
            "已于 2026-10-13 到期（3 天前），请续费或更新到期日。",
            reminders.first { it.entryId == "sub" }.message,
        )
    }

    @Test
    fun subscriptionExpiryRemindersDoNotRequirePassword() {
        val today = LocalDate.of(2026, 10, 16)
        fun entry(id: String, data: VaultItemData) = VaultEntry(id, 1, "2026-10-10T00:00:00Z", data)
        val entries = listOf(
            entry("expired", VaultItemData(VAULT_KIND_SUBSCRIPTION, "过期订阅", expiresOn = "2026-10-13")),
            entry("today", VaultItemData(VAULT_KIND_SUBSCRIPTION, "当天订阅", expiresOn = "2026-10-16")),
            entry("soon", VaultItemData(VAULT_KIND_SUBSCRIPTION, "即将续费", expiresOn = "2026-10-26")),
            entry("far", VaultItemData(VAULT_KIND_SUBSCRIPTION, "远期订阅", expiresOn = "2026-12-15")),
            entry(
                "rotateNoPw",
                VaultItemData(
                    VAULT_KIND_SUBSCRIPTION,
                    "无密码更换",
                    rotateDays = 90,
                    changedAt = "2026-03-30T00:00:00Z",
                ),
            ),
            entry(
                "rotatePw",
                VaultItemData(
                    VAULT_KIND_SUBSCRIPTION,
                    "有密码更换",
                    password = "Str0ng!Pass-word-xyz",
                    rotateDays = 90,
                    changedAt = "2026-03-30T00:00:00Z",
                ),
            ),
        )
        val reminders = collectVaultReminders(entries, today, ZoneOffset.UTC)
        val byEntry = reminders.groupBy({ it.entryId }, { it.type })
        assertEquals(listOf(VaultReminderType.EXPIRED), byEntry["expired"])
        assertEquals(listOf(VaultReminderType.EXPIRED), byEntry["today"])
        assertEquals(listOf(VaultReminderType.EXPIRING), byEntry["soon"])
        assertFalse(byEntry.containsKey("far"))
        assertFalse(byEntry.containsKey("rotateNoPw"))
        assertFalse(byEntry.containsKey("rotatePw"))
        assertEquals("已于 2026-10-13 到期（3 天前），请续费或更新到期日。", reminders.first { it.entryId == "expired" }.message)
        assertEquals("今天到期，请确认续费。", reminders.first { it.entryId == "today" }.message)
        assertEquals("10 天后到期续费（2026-10-26）。", reminders.first { it.entryId == "soon" }.message)
        assertEquals("一次性 / 按量", VAULT_BILLING_LABELS.getValue(VAULT_BILLING_NONE))
    }
}
