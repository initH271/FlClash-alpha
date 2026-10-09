package com.follow.clash.plugins

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.core.net.toUri
import com.follow.clash.common.GlobalState
import java.io.File

internal object DocumentExportRules {

    private const val EXTERNAL_STORAGE_PROVIDER = "com.android.externalstorage.documents"

    fun destinationUri(context: Context, uri: Uri, fileName: String): Uri {
        val current = displayName(uri)
        if (current == fileName) {
            return uri
        }
        val renamed = if (current.isNullOrBlank()) {
            null
        } else {
            runCatching {
                DocumentsContract.renameDocument(context.contentResolver, uri, fileName)
            }.getOrNull()
        }
        if (renamed != null && renamed.lastPathSegment != uri.lastPathSegment) {
            return renamed
        }
        if (uri.lastPathSegment == fileName) {
            return uri
        }
        return uri.buildUpon().appendPath(fileName).build()
    }

    fun treeUriFor(directory: File): Uri? {
        if (!directory.isDirectory) {
            return null
        }
        val documentId = runCatching {
            DocumentsContract.getTreeDocumentId(directory.toUri())
        }.getOrNull() ?: return null
        return DocumentsContract.buildDocumentUri(EXTERNAL_STORAGE_PROVIDER, documentId)
    }

    fun mimeTypeFor(fileName: String): String = when (fileName.substringAfterLast('.', "").lowercase()) {
        "zip" -> "application/zip"
        "json", "jsonl" -> "application/json"
        "log", "txt" -> "text/plain"
        "yaml", "yml" -> "text/yaml"
        else -> "*/*"
    }

    private fun displayName(uri: Uri): String? = runCatching {
        GlobalState.application.contentResolver
            .query(uri, null, null, null, null)?.use { cursor ->
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
            }
    }.getOrNull()
}
