package com.memoisle.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.LedgerCategoryUsage
import com.memoisle.app.data.LedgerEntry
import com.memoisle.app.data.LedgerEntryInput
import com.memoisle.app.data.LedgerSummary
import com.memoisle.app.data.currentLedgerMonth
import com.memoisle.app.data.shiftLedgerMonth
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.MemoApiClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class LedgerUiState(
    val month: String = currentLedgerMonth(),
    val kind: String = "",
    val category: String = "",
    val entries: List<LedgerEntry> = emptyList(),
    val summary: LedgerSummary? = null,
    val categories: List<LedgerCategoryUsage> = emptyList(),
    val loading: Boolean = false,
    val busy: Boolean = false,
    val hasMore: Boolean = false,
    val error: String? = null,
    val message: String? = null,
)

/** 在线记账；取消旧请求，避免切月或退出登录后写回旧账号数据。 */
class LedgerViewModel(private val api: MemoApiClient) : ViewModel() {
    var uiState by mutableStateOf(LedgerUiState())
        private set
    private var loadJob: Job? = null
    private var mutationJob: Job? = null

    fun reset() {
        loadJob?.cancel()
        mutationJob?.cancel()
        uiState = LedgerUiState()
    }

    fun changeMonth(delta: Long) {
        if (uiState.busy) return
        val month = shiftLedgerMonth(uiState.month, delta)
        if (month < "1900-01" || month > "2100-12") return
        uiState = uiState.copy(month = month)
        load()
    }

    fun currentMonth() {
        if (uiState.busy) return
        uiState = uiState.copy(month = currentLedgerMonth())
        load()
    }

    fun filter(kind: String, category: String) {
        if (uiState.busy) return
        uiState = uiState.copy(kind = kind, category = category)
        load()
    }

    fun load() {
        if (uiState.busy) return
        loadJob?.cancel()
        uiState = uiState.copy(loading = true, error = null, message = null,
            entries = emptyList(), summary = null, hasMore = false)
        val snapshot = uiState
        loadJob = viewModelScope.launch {
            try {
                val loaded = read(snapshot)
                uiState = loaded.copy(loading = false)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(loading = false, error = describe(error))
            }
        }
    }

    fun loadMore() {
        if (uiState.busy || uiState.loading || !uiState.hasMore) return
        val snapshot = uiState
        uiState = uiState.copy(loading = true, error = null)
        loadJob = viewModelScope.launch {
            try {
                val rows = withContext(Dispatchers.IO) {
                    api.listLedgerEntries(snapshot.month, snapshot.kind, snapshot.category, snapshot.entries.size)
                }
                uiState = uiState.copy(loading = false,
                    entries = (snapshot.entries + rows).distinctBy { it.id }, hasMore = rows.size == PAGE_SIZE)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(loading = false, error = describe(error))
            }
        }
    }

    fun save(entry: LedgerEntry?, input: LedgerEntryInput, onDone: () -> Unit) {
        mutate(onDone) {
            if (entry == null) api.createLedgerEntry(input)
            else api.updateLedgerEntry(entry.id, input, entry.version)
        }
    }

    fun delete(entry: LedgerEntry, onDone: () -> Unit) {
        mutate(onDone) { api.deleteLedgerEntry(entry.id, entry.version) }
    }

    private fun mutate(onDone: () -> Unit, action: () -> Unit) {
        if (uiState.busy || uiState.loading) return
        loadJob?.cancel()
        uiState = uiState.copy(busy = true, error = null, message = null)
        mutationJob = viewModelScope.launch {
            var message: String
            try {
                withContext(Dispatchers.IO) { action() }
                message = "已保存。"
                // 写入成功就关闭表单，刷新失败时不能让用户重复提交。
                onDone()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (error is ApiException && error.statusCode == 409) {
                    message = "已在其他设备修改，正在重新读取数据，请重新打开后操作。"
                    onDone()
                } else {
                    uiState = uiState.copy(busy = false, error = describe(error))
                    return@launch
                }
            }
            uiState = uiState.copy(entries = emptyList(), summary = null, hasMore = false)
            try {
                uiState = read(uiState).copy(busy = false, message = message)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(busy = false, message = message, error = describe(error))
            }
        }
    }

    private suspend fun read(snapshot: LedgerUiState): LedgerUiState = withContext(Dispatchers.IO) {
        val entries = api.listLedgerEntries(snapshot.month, snapshot.kind, snapshot.category)
        val summary = api.getLedgerSummary(snapshot.month)
        val categories = api.listLedgerCategories()
        snapshot.copy(entries = entries, summary = summary, categories = categories, hasMore = entries.size == PAGE_SIZE)
    }

    private fun describe(error: Exception): String = when (error) {
        is ApiException -> error.detailMessage ?: "操作失败（${error.statusCode}），请重试。"
        is java.io.IOException -> "无法连接服务器。记账仅支持在线使用，请检查网络后重试。"
        else -> "读取或保存失败，请稍后重试。"
    }

    companion object {
        const val PAGE_SIZE = 500
        fun factory(api: MemoApiClient): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = LedgerViewModel(api) as T
        }
    }
}
