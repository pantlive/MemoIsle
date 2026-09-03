package com.memoisle.app.data

import android.content.Context

class AuthTokenStore(context: Context) {
    private val preferences = context.getSharedPreferences(
        "memoisle_auth",
        Context.MODE_PRIVATE,
    )

    fun loadToken(): String? = preferences.getString(KEY_TOKEN, null)

    fun loadUserId(): String? = preferences.getString(KEY_USER_ID, null)

    fun save(token: String, userId: String): Unit {
        preferences.edit()
            .putString(KEY_TOKEN, token)
            .putString(KEY_USER_ID, userId)
            .apply()
    }

    fun clear(): Unit {
        preferences.edit().clear().apply()
    }

    private companion object {
        const val KEY_TOKEN = "access_token"
        const val KEY_USER_ID = "user_id"
    }
}
