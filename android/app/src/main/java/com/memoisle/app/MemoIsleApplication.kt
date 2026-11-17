package com.memoisle.app

import android.app.Application
import com.memoisle.app.data.AuthTokenStore
import com.memoisle.app.data.MemoDatabaseHelper
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.sync.MemoSyncScheduler

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
        // 先放进内存，再挂保存回调，避免启动时把刚读出的令牌又写一遍。
        api.vaultClientToken = tokenStore.loadVaultClientToken()
        api.onVaultClientTokenChanged = { token ->
            if (token.isNullOrBlank()) {
                tokenStore.clearVaultClientToken()
            } else {
                tokenStore.saveVaultClientToken(token)
            }
        }
        repository = MemoRepository(
            database = MemoDatabaseHelper(applicationContext),
            api = api,
            cacheDirectory = applicationContext.cacheDir.toPath(),
            initialActiveUserId = tokenStore.loadUserId(),
            onSyncNeeded = { MemoSyncScheduler.enqueueNow(applicationContext) },
        )
        if (!tokenStore.loadToken().isNullOrBlank() && !tokenStore.loadUserId().isNullOrBlank()) {
            MemoSyncScheduler.schedule(applicationContext)
        }
    }
}
