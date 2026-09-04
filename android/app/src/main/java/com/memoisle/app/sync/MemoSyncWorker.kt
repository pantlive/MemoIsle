package com.memoisle.app.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.memoisle.app.MemoIsleApplication
import com.memoisle.app.network.ApiException
import kotlinx.coroutines.CancellationException

class MemoSyncWorker(
    context: Context,
    workerParameters: WorkerParameters,
) : CoroutineWorker(context, workerParameters) {
    override suspend fun doWork(): Result {
        val application = applicationContext as? MemoIsleApplication
            ?: return Result.failure()
        val token = application.tokenStore.loadToken()
        val userId = application.tokenStore.loadUserId()
        if (token.isNullOrBlank() || userId.isNullOrBlank()) {
            return Result.success()
        }

        // Worker 不把令牌写入 WorkManager 输入数据，避免令牌进入持久化任务记录。
        application.api.accessToken = token
        return try {
            val result = application.repository.refresh(expectedUserId = userId)
            if (result.hasRetryableFailure) Result.retry() else Result.success()
        } catch (error: CancellationException) {
            throw error
        } catch (error: ApiException) {
            if (error.statusCode == 401 || error.statusCode == 403) {
                Result.failure()
            } else {
                Result.retry()
            }
        } catch (error: Exception) {
            Result.retry()
        }
    }
}
