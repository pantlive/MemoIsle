package com.memoisle.app.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object MemoSyncScheduler {
    private const val PERIODIC_WORK_NAME = "memoisle-periodic-sync"
    private const val IMMEDIATE_WORK_NAME = "memoisle-immediate-sync"
    private const val PERIODIC_INTERVAL_MINUTES = 15L
    private const val RETRY_DELAY_SECONDS = 30L

    fun schedule(context: Context): Unit {
        val workManager = WorkManager.getInstance(context.applicationContext)
        val periodicRequest = PeriodicWorkRequestBuilder<MemoSyncWorker>(
            PERIODIC_INTERVAL_MINUTES,
            TimeUnit.MINUTES,
        )
            .setConstraints(periodicConstraints())
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                RETRY_DELAY_SECONDS,
                TimeUnit.SECONDS,
            )
            .build()
        workManager.enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            // 更新约束时替换已有持久化任务，避免旧版本策略一直残留。
            ExistingPeriodicWorkPolicy.UPDATE,
            periodicRequest,
        )
        enqueueNow(context)
    }

    fun enqueueNow(context: Context): Unit {
        val request = OneTimeWorkRequestBuilder<MemoSyncWorker>()
            .setConstraints(immediateConstraints())
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                RETRY_DELAY_SECONDS,
                TimeUnit.SECONDS,
            )
            .build()
        WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
            IMMEDIATE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    fun cancel(context: Context): Unit {
        val workManager = WorkManager.getInstance(context.applicationContext)
        workManager.cancelUniqueWork(PERIODIC_WORK_NAME)
        workManager.cancelUniqueWork(IMMEDIATE_WORK_NAME)
    }

    private fun periodicConstraints(): Constraints {
        return Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            // 后台周期同步避开低电量和存储不足场景，减少系统资源压力。
            .setRequiresBatteryNotLow(true)
            .setRequiresStorageNotLow(true)
            .build()
    }

    private fun immediateConstraints(): Constraints {
        return Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            // 用户刚完成编辑时优先同步，只在存储不足时主动等待。
            .setRequiresStorageNotLow(true)
            .build()
    }
}
