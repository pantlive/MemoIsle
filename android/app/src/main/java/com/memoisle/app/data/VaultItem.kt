package com.memoisle.app.data

import java.security.SecureRandom
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit
import org.json.JSONArray
import org.json.JSONObject

const val VAULT_KIND_LOGIN = "login"
const val VAULT_KIND_SECRET = "secret"
const val VAULT_KIND_RECOVERY = "recovery"

val VAULT_KIND_LABELS = mapOf(
    VAULT_KIND_LOGIN to "账号密码",
    VAULT_KIND_SECRET to "密钥",
    VAULT_KIND_RECOVERY to "恢复码",
)

val VAULT_ROTATE_OPTIONS = listOf(0, 30, 90, 180, 365)
private const val MAX_RECOVERY_CODES = 100

data class RecoveryCode(val code: String, val used: Boolean)

/**
 * 解密后的条目内容，字段与 Web 端相同；只有当前类型用到的字段会写回 JSON。
 * changedAt / rotateDays / expiresOn 是密码提醒设置，和条目一起加密。
 */
data class VaultItemData(
    val kind: String,
    val title: String = "",
    val username: String = "",
    val password: String = "",
    val url: String = "",
    val secret: String = "",
    val account: String = "",
    val codes: List<RecoveryCode> = emptyList(),
    val notes: String = "",
    val skipChecks: Boolean = false,
    val changedAt: String = "",
    val rotateDays: Int = 0,
    val expiresOn: String = "",
) {
    val secretValue: String
        get() = when (kind) {
            VAULT_KIND_LOGIN -> password
            VAULT_KIND_SECRET -> secret
            else -> ""
        }

    fun toJson(): String {
        val json = JSONObject().put("v", 1).put("kind", kind).put("title", title)
        when (kind) {
            VAULT_KIND_LOGIN -> json
                .put("username", username)
                .put("password", password)
                .put("url", url)
                .put("notes", notes)
                .put("skipChecks", skipChecks)
                .putReminderSettings(this)
            VAULT_KIND_SECRET -> json
                .put("secret", secret)
                .put("notes", notes)
                .putReminderSettings(this)
            else -> json
                .put("account", account)
                .put(
                    "codes",
                    JSONArray().apply {
                        codes.forEach { put(JSONObject().put("code", it.code).put("used", it.used)) }
                    },
                )
                .put("notes", notes)
        }
        return json.toString()
    }

    companion object {
        fun empty(kind: String): VaultItemData = VaultItemData(kind = kind)

        /** 解密后按类型补齐字段，旧版本或缺字段的数据也能正常显示。 */
        fun fromJson(text: String): VaultItemData {
            val raw = JSONObject(text)
            val title = raw.optString("title").ifBlank { "未命名" }
            val notes = raw.optString("notes")
            val changedAt = raw.optString("changedAt").takeIf { value ->
                value.isNotBlank() && runCatching { Instant.parse(value) }.isSuccess
            }.orEmpty()
            val rotateDays = raw.optInt("rotateDays", 0).takeIf { it in VAULT_ROTATE_OPTIONS } ?: 0
            val expiresOn = raw.optString("expiresOn").takeIf {
                Regex("""\d{4}-\d{2}-\d{2}""").matches(it)
            }.orEmpty()
            return when (raw.optString("kind")) {
                VAULT_KIND_SECRET -> VaultItemData(
                    kind = VAULT_KIND_SECRET,
                    title = title,
                    secret = raw.optString("secret"),
                    notes = notes,
                    changedAt = changedAt,
                    rotateDays = rotateDays,
                    expiresOn = expiresOn,
                )
                VAULT_KIND_RECOVERY -> {
                    val array = raw.optJSONArray("codes") ?: JSONArray()
                    val codes = buildList {
                        for (index in 0 until array.length()) {
                            val item = array.optJSONObject(index) ?: continue
                            val code = item.optString("code")
                            if (code.isNotEmpty()) add(RecoveryCode(code, item.optBoolean("used", false)))
                        }
                    }
                    VaultItemData(
                        kind = VAULT_KIND_RECOVERY,
                        title = title,
                        account = raw.optString("account"),
                        codes = codes,
                        notes = notes,
                    )
                }
                else -> VaultItemData(
                    kind = VAULT_KIND_LOGIN,
                    title = title,
                    username = raw.optString("username"),
                    password = raw.optString("password"),
                    url = raw.optString("url"),
                    notes = notes,
                    skipChecks = raw.optBoolean("skipChecks", false),
                    changedAt = changedAt,
                    rotateDays = rotateDays,
                    expiresOn = expiresOn,
                )
            }
        }
    }
}

private fun JSONObject.putReminderSettings(data: VaultItemData): JSONObject {
    return put("changedAt", data.changedAt).put("rotateDays", data.rotateDays).put("expiresOn", data.expiresOn)
}

data class VaultEntry(
    val id: String,
    val version: Int,
    val createdAt: String,
    val data: VaultItemData,
)

/** 保存时密码或密钥有变化，就把「上次更换」记为现在；截到毫秒，与网页端 toISOString 的格式一致。 */
fun stampSecretChange(
    previous: VaultItemData?,
    next: VaultItemData,
    now: Instant = Instant.now(),
): VaultItemData {
    val before = previous?.takeIf { it.kind == next.kind }?.secretValue.orEmpty()
    val after = next.secretValue
    return if (after.isNotEmpty() && after != before) next.copy(changedAt = now.truncatedTo(ChronoUnit.MILLIS).toString()) else next
}

/** 网站给的恢复码通常按空格、换行或逗号分隔，粘贴整段即可。 */
fun parseRecoveryCodes(input: String, existing: List<RecoveryCode> = emptyList()): List<RecoveryCode> {
    val seen = existing.map { it.code }.toMutableSet()
    val added = input.split(Regex("""[\s,，;；]+"""))
        .map { it.trim() }
        .filter { it.isNotEmpty() && seen.add(it) }
        .map { RecoveryCode(it, false) }
    return (existing + added).take(MAX_RECOVERY_CODES)
}

private const val LOWER = "abcdefghijkmnopqrstuvwxyz"
private const val UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
private const val DIGITS = "23456789"
private const val SYMBOLS = "!@#$%^&*-_=+?"
private val passwordRandom = SecureRandom()

/** 与 Web 端相同的字符集：去掉易混字符，保证每类字符至少出现一次。 */
fun generateVaultPassword(length: Int = 20): String {
    val groups = listOf(LOWER, UPPER, DIGITS, SYMBOLS)
    val alphabet = groups.joinToString("")
    while (true) {
        val candidate = buildString {
            repeat(length) { append(alphabet[passwordRandom.nextInt(alphabet.length)]) }
        }
        if (groups.all { group -> candidate.any { it in group } }) return candidate
    }
}

enum class VaultReminderType(val label: String) {
    EXPIRED("已过期"),
    EXPIRING("即将到期"),
    ROTATE("该更换了"),
    ROTATE_SOON("快该换了"),
    REUSED("重复密码"),
    WEAK("弱密码"),
    CODES_EMPTY("恢复码用完"),
    CODES_LOW("恢复码不足"),
}

data class VaultReminder(
    val entryId: String,
    val title: String,
    val type: VaultReminderType,
    val danger: Boolean,
    val message: String,
)

private const val EXPIRY_WARN_DAYS = 14
private const val ROTATE_WARN_DAYS = 7
private const val LOW_RECOVERY_CODES = 2

fun isWeakVaultPassword(password: String): Boolean {
    if (password.isEmpty()) return false
    val length = password.codePointCount(0, password.length)
    if (length < 8) return true
    if (password.toSet().size <= 2) return true
    val classes = listOf(
        password.any { it in 'a'..'z' },
        password.any { it in 'A'..'Z' },
        password.any { it.isDigit() },
        password.any { !it.isLetterOrDigit() },
    ).count { it }
    if (length < 12 && classes < 3) return true
    return classes == 1 && length < 16
}

fun lastChangedAt(entry: VaultEntry): String {
    return entry.data.changedAt.ifBlank { entry.createdAt }
}

fun daysSince(iso: String, today: LocalDate, zone: ZoneId): Long {
    val date = runCatching { Instant.parse(iso).atZone(zone).toLocalDate() }.getOrNull() ?: return 0
    return maxOf(0, ChronoUnit.DAYS.between(date, today))
}

/** 与 Web 端相同的提醒规则，只在本机根据解密后的内容计算。 */
fun collectVaultReminders(
    entries: List<VaultEntry>,
    today: LocalDate = LocalDate.now(),
    zone: ZoneId = ZoneId.systemDefault(),
): List<VaultReminder> {
    val reminders = mutableListOf<VaultReminder>()
    fun add(entry: VaultEntry, type: VaultReminderType, danger: Boolean, message: String) {
        reminders += VaultReminder(entry.id, entry.data.title, type, danger, message)
    }
    val byPassword = entries
        .filter { it.data.kind == VAULT_KIND_LOGIN && it.data.password.isNotEmpty() && !it.data.skipChecks }
        .groupBy { it.data.password }

    for (entry in entries) {
        val data = entry.data
        if (data.kind == VAULT_KIND_RECOVERY) {
            if (data.codes.isEmpty()) continue
            val remaining = data.codes.count { !it.used }
            if (remaining == 0) {
                add(entry, VaultReminderType.CODES_EMPTY, true, "恢复码已全部用完，请到网站重新生成一组。")
            } else if (remaining <= LOW_RECOVERY_CODES) {
                add(entry, VaultReminderType.CODES_LOW, false, "只剩 $remaining 个可用恢复码，建议重新生成一组。")
            }
            continue
        }
        if (data.secretValue.isNotEmpty()) {
            if (data.expiresOn.isNotEmpty()) {
                val days = try {
                    ChronoUnit.DAYS.between(today, LocalDate.parse(data.expiresOn))
                } catch (error: DateTimeParseException) {
                    null
                }
                when {
                    days == null -> Unit
                    days < 0 -> add(entry, VaultReminderType.EXPIRED, true, "已于 ${data.expiresOn} 过期（${-days} 天前），请更换。")
                    days == 0L -> add(entry, VaultReminderType.EXPIRED, true, "今天到期，请尽快更换。")
                    days <= EXPIRY_WARN_DAYS -> add(entry, VaultReminderType.EXPIRING, false, "$days 天后到期（${data.expiresOn}）。")
                }
            }
            if (data.rotateDays > 0) {
                val age = daysSince(lastChangedAt(entry), today, zone)
                val left = data.rotateDays - age
                if (left <= 0) {
                    add(entry, VaultReminderType.ROTATE, true, "已 $age 天没有更换，设定为每 ${data.rotateDays} 天换一次。")
                } else if (left <= ROTATE_WARN_DAYS) {
                    add(entry, VaultReminderType.ROTATE_SOON, false, "$left 天后到了更换周期（每 ${data.rotateDays} 天）。")
                }
            }
        }
        if (data.kind == VAULT_KIND_LOGIN && data.password.isNotEmpty() && !data.skipChecks) {
            val others = byPassword[data.password].orEmpty().filter { it.id != entry.id }
            if (others.isNotEmpty()) {
                val titles = others.map { it.data.title }
                val shown = titles.take(2).joinToString("") { "「$it」" }
                val suffix = if (titles.size > 2) "等 ${titles.size} 条" else ""
                add(entry, VaultReminderType.REUSED, true, "和$shown${suffix}用的是同一个密码。")
            }
            if (isWeakVaultPassword(data.password)) {
                add(entry, VaultReminderType.WEAK, false, "密码偏弱，建议用「生成」换成 20 位随机密码。")
            }
        }
    }
    return reminders.sortedWith(compareBy<VaultReminder> { !it.danger }.thenBy { it.title })
}
