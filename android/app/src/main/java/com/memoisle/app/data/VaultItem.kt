package com.memoisle.app.data

import java.security.SecureRandom
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit
import org.json.JSONArray
import org.json.JSONObject
import com.memoisle.app.R
import com.memoisle.app.ui.UiText

const val VAULT_KIND_LOGIN = "login"
const val VAULT_KIND_SECRET = "secret"
const val VAULT_KIND_RECOVERY = "recovery"
const val VAULT_KIND_SERVER = "server"
const val VAULT_KIND_SUBSCRIPTION = "subscription"

const val VAULT_AUTH_PASSWORD = "password"
const val VAULT_AUTH_KEY = "key"

const val VAULT_PROVIDER_CLAUDE = "claude"
const val VAULT_PROVIDER_CHATGPT = "chatgpt"
const val VAULT_PROVIDER_GROK = "grok"
const val VAULT_PROVIDER_OTHER = "other"

const val VAULT_BILLING_MONTHLY = "monthly"
const val VAULT_BILLING_YEARLY = "yearly"
const val VAULT_BILLING_NONE = "none"

const val VAULT_CURRENCY_USD = "USD"
const val VAULT_CURRENCY_CNY = "CNY"

/** 各类型的显示名（字符串资源 id）。 */
val VAULT_KIND_LABELS = mapOf(
    VAULT_KIND_LOGIN to R.string.vault_kind_login,
    VAULT_KIND_SECRET to R.string.vault_kind_secret,
    VAULT_KIND_RECOVERY to R.string.vault_kind_recovery,
    VAULT_KIND_SERVER to R.string.vault_kind_server,
    VAULT_KIND_SUBSCRIPTION to R.string.vault_kind_subscription,
)

val VAULT_PROVIDER_OPTIONS = listOf(
    VAULT_PROVIDER_CLAUDE,
    VAULT_PROVIDER_CHATGPT,
    VAULT_PROVIDER_GROK,
    VAULT_PROVIDER_OTHER,
)

val VAULT_PROVIDER_LABELS = mapOf(
    VAULT_PROVIDER_CLAUDE to R.string.vault_provider_claude,
    VAULT_PROVIDER_CHATGPT to R.string.vault_provider_chatgpt,
    VAULT_PROVIDER_GROK to R.string.vault_provider_grok,
    VAULT_PROVIDER_OTHER to R.string.common_other,
)

val VAULT_BILLING_OPTIONS = listOf(
    VAULT_BILLING_MONTHLY,
    VAULT_BILLING_YEARLY,
    VAULT_BILLING_NONE,
)

val VAULT_BILLING_LABELS = mapOf(
    VAULT_BILLING_MONTHLY to R.string.vault_billing_monthly,
    VAULT_BILLING_YEARLY to R.string.vault_billing_yearly,
    VAULT_BILLING_NONE to R.string.vault_billing_none,
)

private val VAULT_MONEY_PATTERN = Regex("""^\d{1,9}(\.\d{1,2})?$""")
private val VAULT_CURRENCY_PATTERN = Regex("""^[A-Z]{3}$""")

fun normalizeVaultProvider(value: String): String =
    if (value in VAULT_PROVIDER_OPTIONS) value else VAULT_PROVIDER_OTHER

fun normalizeVaultBillingCycle(value: String): String =
    if (value in VAULT_BILLING_OPTIONS) value else VAULT_BILLING_MONTHLY

/** 只接受日历上存在的 YYYY-MM-DD，否则空字符串。 */
fun normalizeVaultDate(value: String): String {
    return value.takeIf { runCatching { LocalDate.parse(it) }.isSuccess }.orEmpty()
}

fun normalizeVaultMoney(value: String): String =
    value.takeIf { VAULT_MONEY_PATTERN.matches(it) }.orEmpty()

fun normalizeVaultCurrency(value: String): String =
    value.takeIf { VAULT_CURRENCY_PATTERN.matches(it) } ?: VAULT_CURRENCY_USD

/** 订阅的默认标题（保存后是用户内容）：品牌名不翻译，「其他」按创建时的界面语言。 */
fun defaultSubscriptionTitle(provider: String, plan: String): String {
    val name = when (normalizeVaultProvider(provider)) {
        VAULT_PROVIDER_CLAUDE -> "Claude"
        VAULT_PROVIDER_CHATGPT -> "ChatGPT"
        VAULT_PROVIDER_GROK -> "Grok"
        else -> ContentDefaults.otherProvider
    }
    val trimmedPlan = plan.trim()
    return if (trimmedPlan.isNotEmpty()) "$name $trimmedPlan" else name
}

/** 列表副标题里的金额：USD→$，CNY→¥，其余用币种代码做前缀。 */
fun formatVaultMoney(currency: String, amount: String): String {
    val code = normalizeVaultCurrency(currency)
    return when (code) {
        VAULT_CURRENCY_USD -> "$$amount"
        VAULT_CURRENCY_CNY -> "¥$amount"
        else -> "$code$amount"
    }
}

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
    // 云服务器：主机、端口、登录用户、认证方式与凭据。
    val host: String = "",
    val port: String = "22",
    val authMethod: String = VAULT_AUTH_PASSWORD,
    val privateKey: String = "",
    /** 引用的 secret 条目 ID；空字符串表示直接填写私钥。 */
    val privateKeyRef: String = "",
    val keyPassphrase: String = "",
    // AI 订阅：服务商、套餐、开始日、计费周期、费用、余额和币种。
    val provider: String = "",
    val plan: String = "",
    val startedOn: String = "",
    val billingCycle: String = "",
    val price: String = "",
    val balance: String = "",
    val currency: String = "",
) {
    /** 只看本条目字段，无法解析对其他密钥的引用；提醒与列表请用 effectiveSecret。 */
    val secretValue: String
        get() = when (kind) {
            VAULT_KIND_LOGIN -> password
            VAULT_KIND_SECRET -> secret
            VAULT_KIND_SERVER -> if (authMethod == VAULT_AUTH_KEY) privateKey else password
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
            VAULT_KIND_SERVER -> json
                .put("host", host)
                .put("port", port)
                .put("username", username)
                .put("authMethod", authMethod)
                .put("password", password)
                // 引用模式下不复制私钥内容，始终写出 privateKeyRef 以便跨端读取。
                .put("privateKey", if (authMethod == VAULT_AUTH_KEY && privateKeyRef.isNotEmpty()) "" else privateKey)
                .put("privateKeyRef", privateKeyRef)
                .put("keyPassphrase", keyPassphrase)
                .put("notes", notes)
                .putReminderSettings(this)
            VAULT_KIND_SUBSCRIPTION -> {
                val item = normalizedSubscription()
                json
                    .put("provider", item.provider)
                    .put("plan", item.plan)
                    .put("account", item.account)
                    .put("startedOn", item.startedOn)
                    .put("billingCycle", item.billingCycle)
                    .put("price", item.price)
                    .put("balance", item.balance)
                    .put("currency", item.currency)
                    .put("notes", item.notes)
                    .put("expiresOn", item.expiresOn)
            }
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
        fun empty(kind: String): VaultItemData = when (kind) {
            VAULT_KIND_SUBSCRIPTION -> VaultItemData(
                kind = kind,
                title = defaultSubscriptionTitle(VAULT_PROVIDER_CLAUDE, ""),
                provider = VAULT_PROVIDER_CLAUDE,
                billingCycle = VAULT_BILLING_MONTHLY,
                currency = VAULT_CURRENCY_USD,
            )
            else -> VaultItemData(kind = kind)
        }

        /** 解密后按类型补齐字段，旧版本或缺字段的数据也能正常显示。 */
        fun fromJson(text: String): VaultItemData {
            val raw = JSONObject(text)
            val title = raw.optString("title").ifBlank { ContentDefaults.untitled }
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
                VAULT_KIND_SERVER -> {
                    val port = raw.optString("port")
                    VaultItemData(
                        kind = VAULT_KIND_SERVER,
                        title = title,
                        host = raw.optString("host"),
                        // 端口只接受 1-65535，越界或 0 回落到 22。
                        port = if (Regex("""[0-9]{1,5}""").matches(port) &&
                            port.toIntOrNull() in 1..65535
                        ) {
                            port
                        } else {
                            "22"
                        },
                        username = raw.optString("username"),
                        authMethod = if (raw.optString("authMethod") == VAULT_AUTH_KEY) {
                            VAULT_AUTH_KEY
                        } else {
                            VAULT_AUTH_PASSWORD
                        },
                        password = raw.optString("password"),
                        privateKey = raw.optString("privateKey"),
                        privateKeyRef = raw.optStrictString("privateKeyRef"),
                        keyPassphrase = raw.optString("keyPassphrase"),
                        notes = notes,
                        changedAt = changedAt,
                        rotateDays = rotateDays,
                        expiresOn = expiresOn,
                    )
                }
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
                VAULT_KIND_SUBSCRIPTION -> VaultItemData(
                    kind = VAULT_KIND_SUBSCRIPTION,
                    title = title,
                    provider = raw.optString("provider"),
                    plan = raw.optString("plan"),
                    account = raw.optString("account"),
                    // 旧订阅密文中的密码、网址和轮换设置不再读入。
                    startedOn = raw.optString("startedOn"),
                    expiresOn = raw.optString("expiresOn"),
                    billingCycle = raw.optString("billingCycle"),
                    price = raw.optString("price"),
                    balance = raw.optString("balance"),
                    currency = raw.optString("currency"),
                    notes = notes,
                ).normalizedSubscription()
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

/** 缺失或非字符串一律当作空，避免把数字等类型当成条目 ID。 */
private fun JSONObject.optStrictString(name: String): String = opt(name) as? String ?: ""

private fun VaultItemData.normalizedSubscription(): VaultItemData = copy(
    provider = normalizeVaultProvider(provider),
    startedOn = normalizeVaultDate(startedOn),
    expiresOn = normalizeVaultDate(expiresOn),
    billingCycle = normalizeVaultBillingCycle(billingCycle),
    price = normalizeVaultMoney(price),
    balance = normalizeVaultMoney(balance),
    currency = normalizeVaultCurrency(currency),
)

data class VaultEntry(
    val id: String,
    val version: Int,
    val createdAt: String,
    val data: VaultItemData,
)

/** 解析后的服务器私钥：value 为有效内容，missing 表示引用已失效。 */
data class ResolvedKey(
    val value: String,
    val refTitle: String = "",
    val missing: Boolean = false,
)

/** 按当前条目列表解析服务器私钥：有引用则取对应密钥，找不到则标记 missing。 */
fun VaultItemData.resolvePrivateKey(entries: List<VaultEntry>): ResolvedKey {
    val ref = privateKeyRef
    if (ref.isEmpty()) return ResolvedKey(value = privateKey)
    val found = entries.firstOrNull { it.id == ref && it.data.kind == VAULT_KIND_SECRET }
    return if (found != null) {
        ResolvedKey(value = found.data.secret, refTitle = found.data.title, missing = false)
    } else {
        ResolvedKey(value = "", refTitle = "", missing = true)
    }
}

/** 有效凭据：服务器在引用密钥时取被引用条目的 secret。 */
fun VaultItemData.effectiveSecret(entries: List<VaultEntry>): String = when (kind) {
    VAULT_KIND_LOGIN -> password
    VAULT_KIND_SECRET -> secret
    VAULT_KIND_SERVER -> if (authMethod == VAULT_AUTH_KEY) resolvePrivateKey(entries).value else password
    else -> ""
}

/** 哪些云服务器引用了这把密钥。 */
fun serversReferencingKey(secretId: String, entries: List<VaultEntry>): List<VaultEntry> {
    if (secretId.isEmpty()) return emptyList()
    return entries.filter { it.data.kind == VAULT_KIND_SERVER && it.data.privateKeyRef == secretId }
}

/** 用于判断凭据是否变化：直接填写用内容，引用密钥用 ref:<id>。 */
fun VaultItemData.credentialIdentity(): String = when (kind) {
    VAULT_KIND_LOGIN -> password
    VAULT_KIND_SECRET -> secret
    VAULT_KIND_SERVER -> when {
        authMethod == VAULT_AUTH_KEY && privateKeyRef.isNotEmpty() -> "ref:$privateKeyRef"
        authMethod == VAULT_AUTH_KEY -> privateKey
        else -> password
    }
    else -> ""
}

/** 保存时密码、密钥或引用目标有变化，就把「上次更换」记为现在；截到毫秒，与网页端 toISOString 的格式一致。 */
fun stampSecretChange(
    previous: VaultItemData?,
    next: VaultItemData,
    now: Instant = Instant.now(),
): VaultItemData {
    val before = previous?.takeIf { it.kind == next.kind }?.credentialIdentity().orEmpty()
    val after = next.credentialIdentity()
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

enum class VaultReminderType(val label: Int) {
    EXPIRED(R.string.common_expired),
    EXPIRING(R.string.vault_reminder_type_expiring),
    ROTATE(R.string.vault_reminder_type_rotate),
    ROTATE_SOON(R.string.vault_reminder_type_rotate_soon),
    REUSED(R.string.vault_reminder_type_reused),
    WEAK(R.string.vault_reminder_type_weak),
    CODES_EMPTY(R.string.vault_reminder_type_codes_empty),
    CODES_LOW(R.string.vault_reminder_type_codes_low),
    MISSING_KEY(R.string.vault_reminder_type_missing_key),
}

data class VaultReminder(
    val entryId: String,
    val title: String,
    val type: VaultReminderType,
    val danger: Boolean,
    val message: UiText,
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

/** 条目的上次更换时间；服务器引用有效密钥时用被引用条目的时间。 */
fun lastChangedAt(entry: VaultEntry, entries: List<VaultEntry> = emptyList()): String {
    val data = entry.data
    if (data.kind == VAULT_KIND_SERVER &&
        data.authMethod == VAULT_AUTH_KEY &&
        data.privateKeyRef.isNotEmpty()
    ) {
        val referenced = entries.firstOrNull { it.id == data.privateKeyRef && it.data.kind == VAULT_KIND_SECRET }
        if (referenced != null) return lastChangedAt(referenced)
    }
    return data.changedAt.ifBlank { entry.createdAt }
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
    fun add(entry: VaultEntry, type: VaultReminderType, danger: Boolean, message: UiText) {
        reminders += VaultReminder(entry.id, entry.data.title, type, danger, message)
    }
    val byPassword = entries
        .filter { it.data.participatesInPasswordChecks() }
        .groupBy { it.data.password }

    for (entry in entries) {
        val data = entry.data
        if (data.kind == VAULT_KIND_RECOVERY) {
            if (data.codes.isEmpty()) continue
            val remaining = data.codes.count { !it.used }
            if (remaining == 0) {
                add(entry, VaultReminderType.CODES_EMPTY, true, UiText.res(R.string.vault_reminder_codes_empty))
            } else if (remaining <= LOW_RECOVERY_CODES) {
                add(entry, VaultReminderType.CODES_LOW, false, UiText.plural(R.plurals.vault_reminder_codes_low, remaining))
            }
            continue
        }
        if (data.kind == VAULT_KIND_SERVER &&
            data.authMethod == VAULT_AUTH_KEY &&
            data.privateKeyRef.isNotEmpty() &&
            data.resolvePrivateKey(entries).missing
        ) {
            add(entry, VaultReminderType.MISSING_KEY, true, UiText.res(R.string.vault_reminder_missing_key))
        }
        val effective = data.effectiveSecret(entries)
        // 订阅的到期提醒只看续费日。
        val checkExpiry = data.kind == VAULT_KIND_SUBSCRIPTION || effective.isNotEmpty()
        if (checkExpiry && data.expiresOn.isNotEmpty()) {
            val days = try {
                ChronoUnit.DAYS.between(today, LocalDate.parse(data.expiresOn))
            } catch (error: DateTimeParseException) {
                null
            }
            val subscription = data.kind == VAULT_KIND_SUBSCRIPTION
            when {
                days == null -> Unit
                days < 0 -> add(
                    entry,
                    VaultReminderType.EXPIRED,
                    true,
                    UiText.plural(
                        if (subscription) R.plurals.vault_reminder_subscription_expired else R.plurals.vault_reminder_expired,
                        (-days).toInt(),
                        data.expiresOn,
                        -days,
                    ),
                )
                days == 0L -> add(
                    entry,
                    VaultReminderType.EXPIRED,
                    true,
                    UiText.res(
                        if (subscription) R.string.vault_reminder_subscription_due_today else R.string.vault_reminder_due_today,
                    ),
                )
                days <= EXPIRY_WARN_DAYS -> add(
                    entry,
                    VaultReminderType.EXPIRING,
                    false,
                    UiText.plural(
                        if (subscription) R.plurals.vault_reminder_subscription_expiring else R.plurals.vault_reminder_expiring,
                        days.toInt(),
                        days,
                        data.expiresOn,
                    ),
                )
            }
        }
        if (effective.isNotEmpty() && data.rotateDays > 0) {
            val age = daysSince(lastChangedAt(entry, entries), today, zone)
            val left = data.rotateDays - age
            if (left <= 0) {
                add(entry, VaultReminderType.ROTATE, true, UiText.plural(R.plurals.vault_reminder_rotate, age.toInt(), age, data.rotateDays))
            } else if (left <= ROTATE_WARN_DAYS) {
                add(entry, VaultReminderType.ROTATE_SOON, false, UiText.plural(R.plurals.vault_reminder_rotate_soon, left.toInt(), left, data.rotateDays))
            }
        }
        if (data.participatesInPasswordChecks()) {
            val others = byPassword[data.password].orEmpty().filter { it.id != entry.id }
            if (others.isNotEmpty()) {
                val titles = others.map { it.data.title }
                val message = when (titles.size) {
                    1 -> UiText.res(R.string.vault_reminder_reused_one, titles[0])
                    2 -> UiText.res(R.string.vault_reminder_reused_two, titles[0], titles[1])
                    else -> UiText.res(R.string.vault_reminder_reused_many, titles[0], titles[1], titles.size)
                }
                add(entry, VaultReminderType.REUSED, true, message)
            }
            if (isWeakVaultPassword(data.password)) {
                add(entry, VaultReminderType.WEAK, false, UiText.res(R.string.vault_reminder_weak))
            }
        }
    }
    return reminders.sortedWith(compareBy<VaultReminder> { !it.danger }.thenBy { it.title })
}

private fun VaultItemData.participatesInPasswordChecks(): Boolean {
    if (password.isEmpty()) return false
    return when (kind) {
        VAULT_KIND_LOGIN -> !skipChecks
        else -> false
    }
}
