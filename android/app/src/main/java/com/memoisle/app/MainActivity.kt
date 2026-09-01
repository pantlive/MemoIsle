package com.memoisle.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.memoisle.app.ui.MemoHomeScreen
import com.memoisle.app.ui.MemoIsleTheme

class MainActivity : ComponentActivity() {
    private val viewModel: MemoViewModel by viewModels {
        MemoViewModel.factory((application as MemoIsleApplication).repository)
    }
    private var sharedText by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        sharedText = extractSharedText(intent)
        enableEdgeToEdge()
        setContent {
            MemoIsleTheme {
                MemoHomeScreen(
                    viewModel = viewModel,
                    sharedText = sharedText,
                    onSharedTextConsumed = { sharedText = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        sharedText = extractSharedText(intent)
    }

    private fun extractSharedText(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_SEND || intent.type != "text/plain") {
            return null
        }
        return intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()?.ifEmpty { null }
    }
}
