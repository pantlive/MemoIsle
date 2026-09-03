package com.memoisle.app

import android.app.Application
import com.memoisle.app.data.AuthTokenStore
import com.memoisle.app.data.MemoDatabaseHelper
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.network.MemoApiClient

class MemoIsleApplication : Application() {
    lateinit var repository: MemoRepository
        private set
    lateinit var api: MemoApiClient
        private set
    lateinit var tokenStore: AuthTokenStore
        private set

    override fun onCreate() {
        super.onCreate()
        api = MemoApiClient(BuildConfig.API_BASE_URL)
        tokenStore = AuthTokenStore(applicationContext)
        repository = MemoRepository(
            database = MemoDatabaseHelper(applicationContext),
            api = api,
            cacheDirectory = applicationContext.cacheDir.toPath(),
        )
    }
}
