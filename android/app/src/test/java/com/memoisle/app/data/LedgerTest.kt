package com.memoisle.app.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Test

class LedgerTest {
    @Test
    fun amountsMatchWebCases() {
        // 与 Web ledger.test.ts 保持同一组输入，金额不经浮点数换算。
        listOf(
            "25" to 2500L, "25.5" to 2550L, "25.50" to 2550L,
            "0.01" to 1L, ".5" to 50L, "12." to 1200L,
            "1,234.56" to 123456L, " ¥1 234.5 " to 123450L,
            "１２．３" to 1230L, "1000000000" to 100_000_000_000L,
        ).forEach { (text, cents) -> assertEquals(text, cents, parseAmountToCents(text)) }
        listOf("", "0", "0.00", ".", "-5", "1.234", "abc", "1e3", "9999999999", "1000000000.01", "12.3.4")
            .forEach { assertNull(it, parseAmountToCents(it)) }
        assertEquals(30L, parseAmountToCents("0.1")!! + parseAmountToCents("0.2")!!)
        assertEquals(1999L, parseAmountToCents("19.99"))
    }

    @Test
    fun formattingAndEditorRoundTripMatchWeb() {
        listOf(0L to "0.00", 1L to "0.01", 2550L to "25.50", 123456L to "1,234.56",
            100_000_000_000L to "1,000,000,000.00", -1500L to "-15.00").forEach { (cents, text) ->
            assertEquals(text, formatCents(cents))
        }
        listOf(2500L to "25", 2550L to "25.50", 1L to "0.01", 5L to "0.05", 123456L to "1234.56")
            .forEach { (cents, text) ->
                assertEquals(text, centsToAmountInput(cents))
                assertEquals(cents, parseAmountToCents(text))
            }
    }

    @Test
    fun monthsCrossYearBoundaries() {
        assertEquals("2025-12", shiftLedgerMonth("2026-01", -1))
        assertEquals("2027-01", shiftLedgerMonth("2026-12", 1))
        assertEquals("2025-01", shiftLedgerMonth("2026-03", -14))
        assertEquals("2028-04", shiftLedgerMonth("2026-03", 25))
    }

    @Test
    fun entryJsonRoundTripKeepsLongAmountsAndNulls() {
        val entry = LedgerEntry("11111111-1111-4111-8111-111111111111", 2,
            LedgerEntryInput("income", 100_000_000_000L, "USD", "2026-11-03", "工资", null, "备注"),
            "2026-11-03T00:00:00Z", "2026-11-03T01:00:00Z")
        assertEquals(entry, LedgerEntry.fromJson(JSONObject(entry.toJson().toString())))
        assertEquals(entry.data, LedgerEntryInput.fromJson(JSONObject(entry.data.toJson().toString())))
        assertNull(LedgerEntryInput.fromJson(entry.data.copy(note = null).toJson()).note)
    }

    @Test
    fun summaryKeepsCurrenciesSeparateAndSupportsLargeTotals() {
        val summary = LedgerSummary.fromJson(JSONObject("""
            {"month":"2026-11","totals":[
              {"currency":"CNY","income_cents":5000000000000000,"expense_cents":100,"balance_cents":4999999999999900,"entry_count":2},
              {"currency":"USD","income_cents":0,"expense_cents":200,"balance_cents":-200,"entry_count":1}
            ],"categories":[{"currency":"USD","kind":"expense","category":"订阅","amount_cents":200,"entry_count":1}]}
        """))
        assertEquals(5_000_000_000_000_000L, summary.totals[0].incomeCents)
        assertEquals(-200L, summary.totals[1].balanceCents)
        assertEquals("订阅", summary.categories.single().category)
        assertEquals(LedgerCategoryUsage("expense", "餐饮", 2),
            LedgerCategoryUsage.fromJson(JSONObject("""{"kind":"expense","category":"餐饮","entry_count":2}""")))
    }

    @Test
    fun rejectsInvalidFieldsBeforeRequest() {
        val valid = LedgerEntryInput(amountCents = 1, occurredOn = "2026-11-03", category = "餐饮")
        assertNull(ledgerValidationError(valid))
        listOf(valid.copy(amountCents = 0), valid.copy(amountCents = LEDGER_MAX_AMOUNT_CENTS + 1),
            valid.copy(kind = "transfer"), valid.copy(currency = "12A"), valid.copy(category = " "),
            valid.copy(category = "类".repeat(31)), valid.copy(occurredOn = "2026-02-30"),
            valid.copy(occurredOn = "1899-12-31"), valid.copy(account = "户".repeat(31)),
            valid.copy(note = "注".repeat(501))).forEach { assertNotNull(ledgerValidationError(it)) }
        assertEquals("USD", normalizeLedgerCurrency(" usd "))
    }
}
