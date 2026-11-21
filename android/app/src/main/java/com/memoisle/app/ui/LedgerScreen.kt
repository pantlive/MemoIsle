package com.memoisle.app.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.ReceiptLong
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.ArrowDropDown
import androidx.compose.material.icons.outlined.ChevronLeft
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.memoisle.app.LedgerViewModel
import com.memoisle.app.data.LedgerCategoryTotal
import com.memoisle.app.data.LedgerCurrencyTotal
import com.memoisle.app.data.LedgerEntry
import com.memoisle.app.data.LedgerEntryInput
import com.memoisle.app.data.LedgerImageDraft
import com.memoisle.app.data.centsToAmountInput
import com.memoisle.app.data.currentLedgerMonth
import com.memoisle.app.data.formatCents
import com.memoisle.app.data.formatLedgerMoney
import com.memoisle.app.data.formatLedgerSigned
import com.memoisle.app.data.ledgerEntrySubtitle
import com.memoisle.app.data.ledgerExpenseCategories
import com.memoisle.app.data.ledgerIncomeCategories
import com.memoisle.app.data.ledgerKindLabel
import com.memoisle.app.data.ledgerValidationError
import com.memoisle.app.data.normalizeLedgerCurrency
import com.memoisle.app.data.parseAmountToCents
import java.time.LocalDate
import java.time.YearMonth

@Composable
fun LedgerScreen(viewModel: LedgerViewModel, onClose: () -> Unit) {
    val state = viewModel.uiState
    var editorOpen by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<LedgerEntry?>(null) }
    var deleting by remember { mutableStateOf<LedgerEntry?>(null) }
    var categoryExpanded by remember { mutableStateOf(false) }
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
    val pickImage = {
        imagePicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = WarmMist,
        topBar = {
            MemoTopBar(
                title = "记账",
                subtitle = "仅在线使用",
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                    }
                },
            ) {
                IconButton(enabled = !disabled, onClick = viewModel::load) {
                    Icon(Icons.Outlined.Refresh, contentDescription = "刷新")
                }
                IconButton(enabled = !disabled, onClick = pickImage) {
                    Icon(Icons.AutoMirrored.Outlined.ReceiptLong, contentDescription = "识别图片")
                }
            }
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { if (!disabled) openEditor(null) },
                containerColor = DeepTeal,
                contentColor = Color.White,
                shape = RoundedCornerShape(18.dp),
            ) { Icon(Icons.Outlined.Add, contentDescription = "记一笔", modifier = Modifier.size(26.dp)) }
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding(),
            contentPadding = PaddingValues(start = 16.dp, top = 4.dp, end = 16.dp, bottom = 104.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                OutlinedTextField(
                    value = quickText,
                    onValueChange = { quickText = it },
                    label = { Text("一句话记账") },
                    placeholder = { Text("如：今天早饭花了10元") },
                    enabled = !state.busy,
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { if (!disabled) submitQuick() }),
                    trailingIcon = {
                        IconButton(
                            enabled = !disabled && quickText.isNotBlank(),
                            onClick = submitQuick,
                        ) {
                            Icon(Icons.AutoMirrored.Outlined.Send, contentDescription = "记下")
                        }
                    },
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        unfocusedContainerColor = SurfaceWhite,
                        focusedContainerColor = SurfaceWhite,
                        unfocusedBorderColor = Border,
                        focusedBorderColor = DeepTeal,
                    ),
                )
            }
            item {
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(
                        enabled = !state.busy && state.month > "1900-01",
                        onClick = { viewModel.changeMonth(-1) },
                    ) { Icon(Icons.Outlined.ChevronLeft, contentDescription = "上月") }
                    Row(
                        Modifier.weight(1f),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(formatLedgerMonthTitle(state.month), style = MaterialTheme.typography.titleMedium)
                        if (state.month != currentLedgerMonth()) {
                            TextButton(
                                enabled = !state.busy,
                                onClick = viewModel::currentMonth,
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                            ) { Text("本月", style = MaterialTheme.typography.labelMedium) }
                        }
                    }
                    IconButton(
                        enabled = !state.busy && state.month < "2100-12",
                        onClick = { viewModel.changeMonth(1) },
                    ) { Icon(Icons.Outlined.ChevronRight, contentDescription = "下月") }
                }
            }
            if (state.loading) item {
                Box(
                    Modifier.fillMaxWidth().padding(vertical = 32.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = DeepTeal)
                }
            }
            state.message?.let { message ->
                item {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(message, Modifier.weight(1f), color = MaterialTheme.colorScheme.primary)
                        state.quickEntry?.let { quick ->
                            // 列表里有更新的版本时用它，避免拿旧版本号保存。
                            TextButton(enabled = !disabled, onClick = {
                                openEditor(state.entries.find { it.id == quick.id } ?: quick)
                            }) { Text("编辑") }
                        }
                    }
                }
            }
            state.error?.let { error ->
                item {
                    Column {
                        Text(error, color = MaterialTheme.colorScheme.error)
                        TextButton(enabled = !disabled, onClick = viewModel::load) { Text("重新读取") }
                    }
                }
            }
            items(state.summary?.totals.orEmpty(), key = { "total-${it.currency}" }) { total ->
                LedgerSummaryCard(total, state.summary?.categories.orEmpty())
            }
            item {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    listOf("" to "全部", "expense" to "支出", "income" to "收入").forEach { (value, label) ->
                        MemoFilterChip(
                            label = label,
                            selected = state.kind == value,
                            onClick = { if (!state.busy) viewModel.filter(value, "") },
                        )
                    }
                    Box {
                        MemoFilterChip(
                            label = "分类：${state.category.ifBlank { "全部" }}",
                            selected = state.category.isNotBlank(),
                            onClick = { if (!state.busy) categoryExpanded = true },
                            leadingIcon = Icons.Outlined.ArrowDropDown,
                        )
                        DropdownMenu(expanded = categoryExpanded, onDismissRequest = { categoryExpanded = false }) {
                            DropdownMenuItem(
                                text = { Text("全部分类") },
                                onClick = { categoryExpanded = false; viewModel.filter(state.kind, "") },
                            )
                            state.categories.filter { state.kind.isBlank() || it.kind == state.kind }
                                .map { it.category }
                                .distinct()
                                .forEach { category ->
                                    DropdownMenuItem(
                                        text = { Text(category) },
                                        onClick = { categoryExpanded = false; viewModel.filter(state.kind, category) },
                                    )
                                }
                        }
                    }
                }
            }
            if (!state.loading && state.error == null && state.entries.isEmpty()) item {
                Text(
                    "这个月还没有流水，点右下角 + 记一笔",
                    Modifier.padding(vertical = 24.dp).fillMaxWidth(),
                    color = TextMuted,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            items(state.entries, key = { "entry-${it.id}" }) { entry ->
                LedgerEntryRow(entry, onClick = { if (!disabled) openEditor(entry) })
            }
            if (state.hasMore) item {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    OutlinedButton(
                        enabled = !disabled,
                        onClick = viewModel::loadMore,
                        shape = RoundedCornerShape(12.dp),
                    ) { Text("加载更多") }
                }
            }
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
            onDelete = editing?.let { entry ->
                {
                    editorOpen = false
                    deleting = entry
                }
            },
        )
    }
    deleting?.let { entry ->
        AlertDialog(
            onDismissRequest = { if (!state.busy) deleting = null },
            title = { Text("永久删除这笔流水？") },
            text = {
                Column {
                    Text("${entry.data.occurredOn} · ${entry.data.category} · ${formatLedgerMoney(entry.data.amountCents, entry.data.currency)}")
                    state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            },
            confirmButton = { TextButton(enabled = !state.busy, onClick = { viewModel.delete(entry) { deleting = null } }) { Text("确认删除") } },
            dismissButton = { TextButton(enabled = !state.busy, onClick = { deleting = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun LedgerSummaryCard(total: LedgerCurrencyTotal, categories: List<LedgerCategoryTotal>) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    val currencyCategories = categories.filter { it.currency == total.currency }
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "本月 · ${total.entryCount} 笔",
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f),
                )
                Text(total.currency, style = MaterialTheme.typography.bodySmall, color = TextMuted)
            }
            Row(Modifier.fillMaxWidth()) {
                LedgerSummaryMetric("收入", formatCents(total.incomeCents), DeepTeal, Modifier.weight(1f))
                LedgerSummaryMetric("支出", formatCents(total.expenseCents), TextStrong, Modifier.weight(1f))
                LedgerSummaryMetric(
                    "结余",
                    formatCents(total.balanceCents),
                    if (total.balanceCents < 0) DangerRed else TextStrong,
                    Modifier.weight(1f),
                )
            }
            Text("不受下方筛选影响", style = MaterialTheme.typography.bodySmall, color = TextMuted)
            if (currencyCategories.isNotEmpty()) {
                TextButton(
                    onClick = { expanded = !expanded },
                    colors = ButtonDefaults.textButtonColors(contentColor = TextMuted),
                    contentPadding = PaddingValues(0.dp),
                ) {
                    Text("分类小计")
                    Icon(
                        if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore,
                        contentDescription = if (expanded) "收起分类小计" else "展开分类小计",
                        modifier = Modifier.size(18.dp),
                    )
                }
                if (expanded) {
                    currencyCategories.forEach { row ->
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(
                                "${row.category} · ${ledgerKindLabel(row.kind)}",
                                style = MaterialTheme.typography.bodySmall,
                                color = TextMuted,
                                modifier = Modifier.weight(1f).padding(end = 12.dp),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(formatCents(row.amountCents), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LedgerSummaryMetric(
    label: String,
    amount: String,
    amountColor: Color,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = TextMuted)
        Text(
            amount,
            style = MaterialTheme.typography.titleMedium,
            color = amountColor,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LedgerEntryRow(entry: LedgerEntry, onClick: () -> Unit) {
    val income = entry.data.kind == "income"
    val subtitle = ledgerEntrySubtitle(entry.data)
    val initial = entry.data.category.trim().firstOrNull()?.toString() ?: "记"
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .background(if (income) TealSoft else SurfaceSubtle, RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    initial,
                    color = if (income) DeepTeal else TextStrong,
                    style = MaterialTheme.typography.titleSmall,
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    entry.data.category,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (subtitle.isNotBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        subtitle,
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            Text(
                formatLedgerSigned(entry.data.kind, entry.data.amountCents),
                color = if (income) DeepTeal else TextStrong,
                style = MaterialTheme.typography.titleSmall,
                textAlign = TextAlign.End,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun LedgerEditor(
    entry: LedgerEntry?,
    draft: LedgerEntryInput?,
    parsedBy: String?,
    month: String,
    busy: Boolean,
    serverError: String?,
    usedCategories: List<Pair<String, String>>,
    onDismiss: () -> Unit,
    onSave: (LedgerEntryInput) -> Unit,
    onDelete: (() -> Unit)? = null,
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

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(if (entry == null) "记一笔" else "编辑流水") },
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
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("expense", "income").forEach { value ->
                        MemoFilterChip(
                            label = ledgerKindLabel(value),
                            selected = kind == value,
                            onClick = {
                                if (!busy) {
                                    kind = value
                                    category = if (value == "income") "工资" else "餐饮"
                                }
                            },
                        )
                    }
                }
                OutlinedTextField(value = amount, onValueChange = { amount = it }, label = { Text("金额") }, enabled = !busy,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = currency, onValueChange = { currency = normalizeLedgerCurrency(it) }, label = { Text("币种，如 CNY / USD") }, enabled = !busy, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = date, onValueChange = { date = it }, label = { Text("日期 YYYY-MM-DD") }, enabled = !busy, singleLine = true, modifier = Modifier.fillMaxWidth())
                Box {
                    OutlinedTextField(
                        value = category,
                        onValueChange = { category = it },
                        label = { Text("分类，可自定义") },
                        enabled = !busy,
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        trailingIcon = {
                            IconButton(enabled = !busy, onClick = { categoryExpanded = true }) {
                                Icon(Icons.Outlined.ArrowDropDown, contentDescription = "选择常用分类")
                            }
                        },
                    )
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
        confirmButton = {
            TextButton(enabled = !busy, onClick = {
                val cents = parseAmountToCents(amount)
                if (cents == null) error = "请输入大于 0、最多两位小数且不超过 10 亿元的金额。"
                else {
                    val data = LedgerEntryInput(kind, cents, normalizeLedgerCurrency(currency), date.trim(), category.trim(),
                        account.trim().ifBlank { null }, note.trim().ifBlank { null })
                    error = ledgerValidationError(data)
                    if (error == null) onSave(data)
                }
            }) { Text(if (busy) "保存中…" else "保存") }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (onDelete != null) {
                    TextButton(
                        enabled = !busy,
                        onClick = onDelete,
                        colors = ButtonDefaults.textButtonColors(contentColor = DangerRed),
                    ) { Text("删除") }
                }
                TextButton(enabled = !busy, onClick = onDismiss) { Text("取消") }
            }
        },
    )
}

private fun formatLedgerMonthTitle(month: String): String {
    val parsed = YearMonth.parse(month)
    return "${parsed.year} 年 ${parsed.monthValue} 月"
}
