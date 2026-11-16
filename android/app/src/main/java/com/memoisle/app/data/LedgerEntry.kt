package com.memoisle.app.data

import java.time.LocalDate
import java.time.YearMonth
import java.util.Locale
import org.json.JSONObject

const val LEDGER_MAX_AMOUNT_CENTS = 100_000_000_000L
val ledgerExpenseCategories = listOf("餐饮", "交通", "购物", "订阅", "住房", "娱乐", "医疗", "其他")
val ledgerIncomeCategories = listOf("工资", "其他")

/** 记账金额统一用 Long 保存分，不经浮点数换算。 */
data class LedgerEntryInput(
    val kind: String = "expense",
    val amountCents: Long,
    val currency: String = "CNY",
    val occurredOn: String,
    val category: String,
    val account: String? = null,
    val note: String? = null,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("kind", kind).put("amount_cents", amountCents)
        .put("currency", currency).put("occurred_on", occurredOn)
        .put("category", category).put("account", account ?: JSONObject.NULL)
        .put("note", note ?: JSONObject.NULL)

    companion object {
        fun fromJson(json: JSONObject): LedgerEntryInput = LedgerEntryInput(
            kind = json.getString("kind"), amountCents = json.getLong("amount_cents"),
            currency = json.getString("currency"), occurredOn = json.getString("occurred_on"),
            category = json.getString("category"),
            account = if (json.isNull("account")) null else json.getString("account"),
            note = if (json.isNull("note")) null else json.getString("note"),
        )
    }
}

data class LedgerEntry(
    val id: String,
    val version: Int,
    val data: LedgerEntryInput,
    val createdAt: String,
    val updatedAt: String,
) {
    fun toJson(): JSONObject = data.toJson().put("id", id).put("version", version)
        .put("created_at", createdAt).put("updated_at", updatedAt)

    companion object {
        fun fromJson(json: JSONObject): LedgerEntry = LedgerEntry(
            id = json.getString("id"), version = json.getInt("version"),
            data = LedgerEntryInput.fromJson(json),
            createdAt = json.getString("created_at"), updatedAt = json.getString("updated_at"),
        )
    }
}

/** 一句话记下的一笔；parsedBy 为 "llm"（服务端配置的本地大模型）或 "rule"（固定规则）。 */
data class LedgerQuickResult(val entry: LedgerEntry, val parsedBy: String) {
    val byLocalModel: Boolean get() = parsedBy == "llm"

    companion object {
        fun fromJson(json: JSONObject): LedgerQuickResult = LedgerQuickResult(
            entry = LedgerEntry.fromJson(json),
            // 旧版服务端不返回 parsed_by，按规则识别处理。
            parsedBy = if (json.isNull("parsed_by")) "rule" else json.getString("parsed_by"),
        )
    }
}

data class LedgerCurrencyTotal(
    val currency: String, val incomeCents: Long, val expenseCents: Long,
    val balanceCents: Long, val entryCount: Int,
)

data class LedgerCategoryTotal(
    val currency: String, val kind: String, val category: String,
    val amountCents: Long, val entryCount: Int,
)

data class LedgerCategoryUsage(val kind: String, val category: String, val entryCount: Int) {
    companion object {
        fun fromJson(json: JSONObject): LedgerCategoryUsage = LedgerCategoryUsage(
            json.getString("kind"), json.getString("category"), json.getInt("entry_count"),
        )
    }
}

data class LedgerSummary(
    val month: String,
    val totals: List<LedgerCurrencyTotal>,
    val categories: List<LedgerCategoryTotal>,
) {
    companion object {
        fun fromJson(json: JSONObject): LedgerSummary {
            val totals = json.getJSONArray("totals")
            val categories = json.getJSONArray("categories")
            return LedgerSummary(
                month = json.getString("month"),
                totals = List(totals.length()) { index ->
                    val row = totals.getJSONObject(index)
                    LedgerCurrencyTotal(row.getString("currency"), row.getLong("income_cents"),
                        row.getLong("expense_cents"), row.getLong("balance_cents"), row.getInt("entry_count"))
                },
                categories = List(categories.length()) { index ->
                    val row = categories.getJSONObject(index)
                    LedgerCategoryTotal(row.getString("currency"), row.getString("kind"),
                        row.getString("category"), row.getLong("amount_cents"), row.getInt("entry_count"))
                },
            )
        }
    }
}

/** 与 Web 使用同一套输入规则，允许千分位、货币符号和全角数字。 */
fun parseAmountToCents(input: String): Long? {
    val normalized = input.map { char ->
        when (char) {
            in '０'..'９' -> '0' + (char - '０')
            '．' -> '.'
            else -> char
        }
    }.filterNot { it.isWhitespace() || it in ",，¥￥$" }.joinToString("")
    val text = if (normalized.startsWith('.')) "0$normalized" else normalized
    val match = Regex("^(\\d{1,9}|1000000000)(?:\\.(\\d{0,2}))?$").matchEntire(text) ?: return null
    val whole = match.groupValues[1].toLong()
    val fraction = match.groupValues[2].padEnd(2, '0').toLong()
    return (whole * 100 + fraction).takeIf { it in 1..LEDGER_MAX_AMOUNT_CENTS }
}

fun formatCents(cents: Long): String {
    val absolute = kotlin.math.abs(cents)
    val whole = (absolute / 100).toString().reversed().chunked(3).joinToString(",").reversed()
    return "${if (cents < 0) "-" else ""}$whole.${(absolute % 100).toString().padStart(2, '0')}"
}

fun centsToAmountInput(cents: Long): String {
    val absolute = kotlin.math.abs(cents)
    val fraction = absolute % 100
    return if (fraction == 0L) (absolute / 100).toString()
    else "${absolute / 100}.${fraction.toString().padStart(2, '0')}"
}

fun formatLedgerMoney(cents: Long, currency: String): String = "$currency ${formatCents(cents)}"
fun ledgerKindLabel(kind: String): String = if (kind == "income") "收入" else "支出"
fun currentLedgerMonth(): String = YearMonth.now().toString()
fun shiftLedgerMonth(month: String, delta: Long): String = YearMonth.parse(month).plusMonths(delta).toString()

/** 客户端先校验，服务端仍负责最终校验与账号隔离。 */
fun ledgerValidationError(data: LedgerEntryInput): String? {
    if (data.kind !in listOf("income", "expense")) return "请选择收入或支出。"
    if (data.amountCents !in 1..LEDGER_MAX_AMOUNT_CENTS) return "金额需大于 0 且不超过 10 亿元。"
    if (!Regex("[A-Z]{3}").matches(data.currency)) return "币种应为三位字母，如 CNY。"
    val date = runCatching { LocalDate.parse(data.occurredOn) }.getOrNull()
    if (date == null || date.year !in 1900..2100) return "日期应为 YYYY-MM-DD，年份范围 1900–2100。"
    if (data.category.isBlank() || data.category.codePointCount(0, data.category.length) > 30) return "分类需为 1–30 个字。"
    if ((data.account?.codePointCount(0, data.account.length) ?: 0) > 30) return "账户最多 30 个字。"
    if ((data.note?.codePointCount(0, data.note.length) ?: 0) > 500) return "备注最多 500 个字。"
    return null
}

fun normalizeLedgerCurrency(currency: String): String = currency.trim().uppercase(Locale.ROOT)
