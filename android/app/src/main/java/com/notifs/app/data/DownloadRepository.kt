package com.notifs.app.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class AppDownloadItem(
    val id: String,
    val filename: String,
    val state: String,
    val bytesDownloaded: Long = 0L,
    val totalBytes: Long? = null,
    val percentage: Float? = null,
    val speedBytesSec: Long = 0L,
    val etaSeconds: Long? = null,
    val updatedAt: Long = System.currentTimeMillis()
)

object DownloadRepository {
    private val _downloads = MutableStateFlow<List<AppDownloadItem>>(emptyList())
    val downloadsFlow: StateFlow<List<AppDownloadItem>> = _downloads.asStateFlow()

    fun updateDownloads(items: List<AppDownloadItem>) {
        _downloads.value = items
    }

    fun clear() {
        _downloads.value = emptyList()
    }
}
