package com.memoisle.app.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.memoisle.app.LedgerViewModel
import com.memoisle.app.data.LedgerEntry
import com.memoisle.app.data.LedgerEntryInput
import com.memoisle.app.data.LedgerImageDraft
import com.memoisle.app.data.centsToAmountInput
import com.memoisle.app.data.currentLedgerMonth
import com.memoisle.app.data.formatLedgerMoney
import com.memoisle.app.data.ledgerExpenseCategories
import com.memoisle.app.data.ledgerIncomeCategories
import com.memoisle.app.data.ledgerKindLabel
import com.memoisle.app.data.ledgerValidationError
import com.memoisle.app.data.normalizeLedgerCurrency
import com.memoisle.app.data.parseAmountToCents
import java.time.LocalDate

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerScreen(viewModel: LedgerViewModel, onClose: () -> Unit) {
    val state = viewModel.uiState
    var editorOpen by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<LedgerEntry?>(null) }
    var deleting by remember { mutableStateOf<LedgerEntry?>(null) }
    var categoryExpanded by remember { mutableStateOf(false) }
    var showCategoryTotals by rememberSaveable { mutableStateOf(false) }
    var quickText by rememberSaveable { mutableStateOf("") }
    var imageDraft by remember { mutableStateOf<LedgerEntryInput?>(null) }
    var imageSource by remember { mutableStateOf<String?>(null) }
    var editorNonce by remember { mutableIntStateOf(0) }
    val context = LocalContext.current
    val imagePicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) {
            viewModel.recognizeImage(uri, context.contentResolver) { draft ->
                editing = null
                imageDraft = draft.data
                imageSource = draft.parsedBy
                editorNonce += 1
                editorOpen = true
            }
        }
    }
    LaunchedEffect(Unit) { viewModel.load() }
    BackHandler { onClose() }
    val disabled = state.busy || state.loading
    // 识别失败时不清空，方便改一改再记。
    val submitQuick = { viewModel.quickAdd(quickText) { quickText = "" } }
    fun openEditor(entry: LedgerEntry?, draft: LedgerImageDraft? = null) {
        editing = entry
        imageDraft = if (entry == null) draft?.data else null
        imageSource = if (entry == null) draft?.parsedBy else null
        editorNonce += 1
        editorOpen = true
    }

    Scaffold(topBar = {
        TopAppBar(title = { Text("记账") }, navigationIcon = {
            IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") }
        }, actions = {
            TextButton(enabled = !disabled, onClick = viewModel::load) { Text("刷新") }
            TextButton(enabled = !disabled, onClick = { openEditor(null) }) { Text("记一笔") }
        })
    }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = quickText, onValueChange = { quickText = it },
                        label = { Text("一句话记账") }, placeholder = { Text("如：今天早饭花了10元") },
                        enabled = !state.busy, singleLine = true, modifier = Modifier.weight(1f),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { if (!disabled) submitQuick() }))
                    Button(enabled = !disabled && quickText.isNotBlank(), onClick = submitQuick) { Text("记下") }
                    TextButton(enabled = !disabled, onClick = {
                        imagePicker.launch(
                            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
                        )
                    }) { Text("识别图片") }
                }
            }
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(enabled = !state.busy && state.month > "1900-01", onClick = { viewModel.changeMonth(-1) }) { Text("上月") }
                    Column {
                        Text(state.month, style = MaterialTheme.typography.titleLarge)
                        TextButton(enabled = !state.busy, onClick = viewModel::currentMonth) { Text("回到本月") }
                    }
                    TextButton(enabled = !state.busy && state.month < "2100-12", onClick = { viewModel.changeMonth(1) }) { Text("下月") }
                }
            }
            if (state.loading) item { CircularProgressIndicator() }
            state.message?.let { message -> item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(message, Modifier.weight(1f))
                    state.quickEntry?.let { quick ->
                        // 列表里有更新的版本时用它，避免拿旧版本号保存。
                        TextButton(enabled = !disabled, onClick = {
                            openEditor(state.entries.find { it.id == quick.id } ?: quick)
                        }) { Text("编辑") }
                    }
                }
            } }
            state.error?.let { error -> item {
                Text(error, color = MaterialTheme.colorScheme.error)
                TextButton(enabled = !disabled, onClick = viewModel::load) { Text("重新读取") }
            } }
            items(state.summary?.totals.orEmpty(), key = { "total-${it.currency}" }) { total ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("${total.currency} · ${total.entryCount} 笔", style = MaterialTheme.typography.titleMedium)
                        Text("收入  ${formatLedgerMoney(total.incomeCents, total.currency)}")
                        Text("支出  ${formatLedgerMoney(total.expenseCents, total.currency)}")
                        Text("结余  ${formatLedgerMoney(total.balanceCents, total.currency)}", style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
            if (!state.summary?.categories.isNullOrEmpty()) item {
                TextButton(onClick = { showCategoryTotals = !showCategoryTotals }) { Text(if (showCategoryTotals) "收起分类小计" else "查看分类小计") }
            }
            if (showCategoryTotals) items(state.summary?.categories.orEmpty(), key = { "category-${it.currency}-${it.kind}-${it.category}" }) { total ->
                Text("${total.category} · ${ledgerKindLabel(total.kind)} · ${formatLedgerMoney(total.amountCents, total.currency)}")
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("" to "全部", "expense" to "支出", "income" to "收入").forEach { (value, label) ->
                        TextButton(enabled = !state.busy, onClick = { viewModel.filter(value, "") }) {
                            Text(if (state.kind == value) "✓ $label" else label)
                        }
                    }
                }
                Column {
                    TextButton(enabled = !state.busy, onClick = { categoryExpanded = true }) { Text("分类：${state.category.ifBlank { "全部" }}") }
                    DropdownMenu(expanded = categoryExpanded, onDismissRequest = { categoryExpanded = false }) {
                        DropdownMenuItem(text = { Text("全部分类") }, onClick = { categoryExpanded = false; viewModel.filter(state.kind, "") })
                        state.categories.filter { state.kind.isBlank() || it.kind == state.kind }.map { it.category }.distinct().forEach { category ->
                            DropdownMenuItem(text = { Text(category) }, onClick = { categoryExpanded = false; viewModel.filter(state.kind, category) })
                        }
                    }
                }
                Text("汇总包含当月全部收支", style = MaterialTheme.typography.bodySmall)
            }
            if (!state.loading && state.error == null && state.entries.isEmpty()) item {
                Text("这个月还没有符合条件的流水，点击「记一笔」开始记录。", Modifier.padding(vertical = 24.dp))
            }
            items(state.entries, key = { "entry-${it.id}" }) { entry ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(entry.data.category, style = MaterialTheme.typography.titleMedium)
                        Text("${entry.data.occurredOn}${entry.data.account?.let { " · $it" }.orEmpty()}", style = MaterialTheme.typography.bodySmall)
                        Text("${if (entry.data.kind == "income") "+" else "-"}${formatLedgerMoney(entry.data.amountCents, entry.data.currency)}",
                            color = if (entry.data.kind == "income") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                        entry.data.note?.let { Text(it) }
                        Row {
                            TextButton(enabled = !disabled, onClick = { openEditor(entry) }) { Text("编辑") }
                            TextButton(enabled = !disabled, onClick = { deleting = entry }) { Text("删除") }
                        }
                    }
                }
            }
            if (state.hasMore) item { Button(enabled = !disabled, onClick = viewModel::loadMore) { Text("加载更多流水") } }
            item { Text("记账仅支持在线使用。", Modifier.padding(vertical = 12.dp), style = MaterialTheme.typography.bodySmall) }
        }
    }
    if (editorOpen) key(editorNonce) {
        LedgerEditor(
            entry = editing,
            draft = if (editing == null) imageDraft else null,
            parsedBy = if (editing == null) imageSource else null,
            month = state.month, busy = state.busy, serverError = state.error,
            usedCategories = state.categories.map { it.kind to it.category },
            onDismiss = { editorOpen = false },
            onSave = { input -> viewModel.save(editing, input) { editorOpen = false } },
        )
    }
    deleting?.let { entry ->
        AlertDialog(onDismissRequest = { if (!state.busy) deleting = null },
            title = { Text("永久删除这笔流水？") },
            text = { Column {
                Text("${entry.data.occurredOn} · ${entry.data.category} · ${formatLedgerMoney(entry.data.amountCents, entry.data.currency)}")
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            } },
            confirmButton = { TextButton(enabled = !state.busy, onClick = { viewModel.delete(entry) { deleting = null } }) { Text("确认删除") } },
            dismissButton = { TextButton(enabled = !state.busy, onClick = { deleting = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun LedgerEditor(
    entry: LedgerEntry?, draft: LedgerEntryInput?, parsedBy: String?, month: String, busy: Boolean,
    serverError: String?, usedCategories: List<Pair<String, String>>, onDismiss: () -> Unit,
    onSave: (LedgerEntryInput) -> Unit,
) {
    val seed = entry?.data ?: draft
    var kind by rememberSaveable { mutableStateOf(seed?.kind ?: "expense") }
    var amount by rememberSaveable { mutableStateOf(seed?.let { centsToAmountInput(it.amountCents) }.orEmpty()) }
    var currency by rememberSaveable { mutableStateOf(seed?.currency ?: "CNY") }
    var date by rememberSaveable { mutableStateOf(seed?.occurredOn ?: if (month == currentLedgerMonth()) LocalDate.now().toString() else "$month-01") }
    var category by rememberSaveable { mutableStateOf(seed?.category ?: "餐饮") }
    var account by rememberSaveable { mutableStateOf(seed?.account.orEmpty()) }
    var note by rememberSaveable { mutableStateOf(seed?.note.orEmpty()) }
    var error by remember { mutableStateOf<String?>(null) }
    var categoryExpanded by remember { mutableStateOf(false) }

    AlertDialog(onDismissRequest = { if (!busy) onDismiss() }, title = { Text(if (entry == null) "记一笔" else "编辑流水") },
        text = {
            Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                parsedBy?.let { source ->
                    val label = when (source) {
                        "vision" -> "视觉模型"
                        "llm" -> "本地模型"
                        "rule" -> "规则"
                        else -> source
                    }
                    Text("识别来源：$label。请核对后再保存，尚未写入。")
                }
                Row {
                    listOf("expense", "income").forEach { value -> TextButton(enabled = !busy, onClick = {
                        kind = value; category = if (value == "income") "工资" else "餐饮"
                    }) { Text("${if (kind == value) "✓ " else ""}${ledgerKindLabel(value)}") } }
                }
                OutlinedTextField(value = amount, onValueChange = { amount = it }, label = { Text("金额") }, enabled = !busy,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = currency, onValueChange = { currency = normalizeLedgerCurrency(it) }, label = { Text("币种，如 CNY / USD") }, enabled = !busy, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = date, onValueChange = { date = it }, label = { Text("日期 YYYY-MM-DD") }, enabled = !busy, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = category, onValueChange = { category = it }, label = { Text("分类，可自定义") }, enabled = !busy, singleLine = true, modifier = Modifier.fillMaxWidth())
                Column {
                    TextButton(enabled = !busy, onClick = { categoryExpanded = true }) { Text("选择常用分类") }
                    DropdownMenu(expanded = categoryExpanded, onDismissRequest = { categoryExpanded = false }) {
                        val presets = if (kind == "income") ledgerIncomeCategories else ledgerExpenseCategories
                        (presets + usedCategories.filter { it.first == kind }.map { it.second }).distinct().forEach { value ->
                            DropdownMenuItem(text = { Text(value) }, onClick = { category = value; categoryExpanded = false })
                        }
                    }
                }
                OutlinedTextField(value = account, onValueChange = { account = it }, label = { Text("账户（选填）") }, enabled = !busy, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = note, onValueChange = { note = it }, label = { Text("备注（选填）") }, enabled = !busy, minLines = 2, modifier = Modifier.fillMaxWidth())
                (error ?: serverError)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { TextButton(enabled = !busy, onClick = {
            val cents = parseAmountToCents(amount)
            if (cents == null) error = "请输入大于 0、最多两位小数且不超过 10 亿元的金额。"
            else {
                val data = LedgerEntryInput(kind, cents, normalizeLedgerCurrency(currency), date.trim(), category.trim(),
                    account.trim().ifBlank { null }, note.trim().ifBlank { null })
                error = ledgerValidationError(data)
                if (error == null) onSave(data)
            }
        }) { Text(if (busy) "保存中…" else "保存") } },
        dismissButton = { TextButton(enabled = !busy, onClick = onDismiss) { Text("取消") } },
    )
}
