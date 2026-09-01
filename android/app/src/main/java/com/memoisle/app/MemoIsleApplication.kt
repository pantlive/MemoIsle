package com.memoisle.app

import android.app.Application
import com.memoisle.app.data.MemoDatabaseHelper
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.network.MemoApiClient

class MemoIsleApplication : Application() {
    lateinit var repository: MemoRepository
        private set

    override fun onCreate() {
        super.onCreate()
        repository = MemoRepository(
            database = MemoDatabaseHelper(applicationContext),
            api = MemoApiClient(BuildConfig.API_BASE_URL),
        )
    }
}
