package com.memoisle.app.data

import java.time.LocalDate
import java.time.YearMonth
import java.util.Locale
import org.json.JSONObject
import com.memoisle.app.R
import com.memoisle.app.ui.UiText

const val LEDGER_MAX_AMOUNT_CENTS = 100_000_000_000L
/** 预置分类（字符串资源 id）：按当前界面语言显示，分类是自由文本，选中后按显示的文字保存。 */
val ledgerExpenseCategories = listOf(
    R.string.ledger_category_food,
    R.string.ledger_category_transport,
    R.string.ledger_category_shopping,
    R.string.ledger_category_subscription,
    R.string.ledger_category_housing,
    R.string.ledger_category_entertainment,
    R.string.ledger_category_medical,
    R.string.common_other,
)
val ledgerIncomeCategories = listOf(R.string.ledger_category_salary, R.string.common_other)

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

/**
 * 图片识别出的草稿，尚未写入。
 * parsedBy 为 "vision"（本地视觉模型）、"llm"（OCR 后的本地文本模型）或 "rule"（规则）。
 */
data class LedgerImageDraft(val data: LedgerEntryInput, val parsedBy: String) {
    companion object {
        fun fromJson(json: JSONObject): LedgerImageDraft = LedgerImageDraft(
            data = LedgerEntryInput.fromJson(json),
            parsedBy = json.getString("parsed_by"),
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

/** 列表金额：按收支带正负号，不重复写币种。 */
fun formatLedgerSigned(kind: String, cents: Long): String {
    val amount = formatCents(kotlin.math.abs(cents))
    return if (kind == "income") "+$amount" else "-$amount"
}

/** 流水副标题：日期 · 账户 · 备注，空值跳过，换行压成空格。 */
fun ledgerEntrySubtitle(data: LedgerEntryInput): String = listOfNotNull(
    data.occurredOn.takeIf { it.isNotBlank() },
    data.account?.trim()?.takeIf { it.isNotBlank() },
    data.note?.replace(Regex("\\s+"), " ")?.trim()?.takeIf { it.isNotBlank() },
).joinToString(" · ")

fun ledgerKindLabel(kind: String): Int = if (kind == "income") R.string.ledger_kind_income else R.string.ledger_kind_expense
fun currentLedgerMonth(): String = YearMonth.now().toString()
fun shiftLedgerMonth(month: String, delta: Long): String = YearMonth.parse(month).plusMonths(delta).toString()

/** 客户端先校验，服务端仍负责最终校验与账号隔离。 */
fun ledgerValidationError(data: LedgerEntryInput): UiText? {
    if (data.kind !in listOf("income", "expense")) return UiText.res(R.string.ledger_error_kind)
    if (data.amountCents !in 1..LEDGER_MAX_AMOUNT_CENTS) return UiText.res(R.string.ledger_error_amount)
    if (!Regex("[A-Z]{3}").matches(data.currency)) return UiText.res(R.string.ledger_error_currency)
    val date = runCatching { LocalDate.parse(data.occurredOn) }.getOrNull()
    if (date == null || date.year !in 1900..2100) return UiText.res(R.string.ledger_error_date)
    if (data.category.isBlank() || data.category.codePointCount(0, data.category.length) > 30) {
        return UiText.res(R.string.ledger_error_category)
    }
    if ((data.account?.codePointCount(0, data.account.length) ?: 0) > 30) return UiText.res(R.string.ledger_error_account)
    if ((data.note?.codePointCount(0, data.note.length) ?: 0) > 500) return UiText.res(R.string.ledger_error_note)
    return null
}

fun normalizeLedgerCurrency(currency: String): String = currency.trim().uppercase(Locale.ROOT)
