package com.follow.clash.plugins

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import com.follow.clash.common.GlobalState
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.MethodChannel.MethodCallHandler
import io.flutter.plugin.common.MethodChannel.Result
import io.flutter.plugin.common.PluginRegistry
import java.io.FileNotFoundException
import java.io.OutputStream

/**
 * Owns the ACTION_CREATE_DOCUMENT hop and the chunked write that follows it.
 * A plugin-side handler rather than a call into file_picker, which answers with
 * `renamedUri.path`: a `content://` path carries neither the scheme nor the
 * authority, so the export failed on a path no provider owns after the user had
 * chosen a destination. Chunked because a provider may buffer the whole stream.
 */
internal class DocumentExportHandler(
    private val activity: () -> Activity?,
) : PluginRegistry.ActivityResultListener,
    MethodCallHandler {

    private var pendingResult: Result? = null

    private var pendingFileName: String? = null

    private var streamUri: Uri? = null

    private var stream: OutputStream? = null

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "createExportDocument" -> createDocument(call, result)
            "writeExportChunk" -> writeChunk(call, result)
            "renameExportDocument" -> renameDocument(call, result)
            else -> result.notImplemented()
        }
    }

    private fun createDocument(call: MethodCall, result: Result) {
        val target = activity()
        if (target == null) {
            result.error("EXPORT_NO_ACTIVITY", "No activity can show the save dialog", null)
            return
        }
        if (pendingResult != null) {
            // Settling it keeps a caller whose activity is gone from waiting.
            reply { pendingResult?.error("EXPORT_BUSY", "A save dialog is already open", null) }
            resetDialog()
            result.error("EXPORT_BUSY", "A save dialog is already open", null)
            return
        }
        val fileName = call.argument<String>("fileName")
        if (fileName.isNullOrBlank()) {
            result.error("EXPORT_NO_NAME", "An export file name is required", null)
            return
        }
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = DocumentExportRules.mimeTypeFor(fileName)
            putExtra(Intent.EXTRA_TITLE, fileName)
            val initial = call.argument<String>("initialUri")
            if (!initial.isNullOrEmpty() && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                putExtra(DocumentsContract.EXTRA_INITIAL_URI, Uri.parse(initial))
            }
        }
        pendingResult = result
        pendingFileName = fileName
        try {
            target.startActivityForResult(intent, REQUEST_CODE)
        } catch (error: ActivityNotFoundException) {
            resetDialog()
            result.error("EXPORT_NO_PROVIDER", error.message, null)
        } catch (error: Exception) {
            resetDialog()
            result.error("EXPORT_START_FAILED", error.toString(), null)
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != REQUEST_CODE) {
            return false
        }
        val uri = if (resultCode == Activity.RESULT_OK) data?.data else null
        if (uri == null) {
            reply { pendingResult?.success(null) }
            resetDialog()
            return true
        }
        val opened = runCatching {
            GlobalState.application.contentResolver.openOutputStream(uri, "wt")
        }.getOrNull()
        if (opened == null) {
            reply {
                pendingResult?.error(
                    "EXPORT_NO_TARGET",
                    "The chosen destination cannot be written",
                    null,
                )
            }
            resetDialog()
            return true
        }
        // Proves the grant; the stream reopens per chunk.
        runCatching { opened.close() }
        val wanted = pendingFileName
        val destination = if (wanted.isNullOrEmpty()) {
            uri
        } else {
            DocumentExportRules.destinationUri(GlobalState.application, uri, wanted)
        }
        reply { pendingResult?.success(destination.toString()) }
        resetDialog()
        return true
    }

    /// The engine outlives an activity rebuild, this dialog answer does not.
    fun detachActivity() {
        reply { pendingResult?.error("EXPORT_INTERRUPTED", "The activity was recreated", null) }
        resetDialog()
    }

    private fun writeChunk(call: MethodCall, result: Result) {
        val uri = call.argument<String>("uri")?.let(Uri::parse)
        val bytes = call.argument<ByteArray>("bytes")
        if (uri == null || bytes == null) {
            result.error("EXPORT_BAD_REQUEST", "A destination URI and bytes are required", null)
            return
        }
        val first = call.argument<Boolean>("first") == true
        val done = call.argument<Boolean>("done") == true
        try {
            if (first || stream == null || streamUri != uri) {
                closeStream()
                stream = GlobalState.application.contentResolver.openOutputStream(uri, "wt")
                    ?: throw FileNotFoundException("No output stream for $uri")
                streamUri = uri
            }
            if (bytes.isNotEmpty()) {
                stream?.write(bytes)
            }
            if (done) {
                closeStream()
            }
            result.success(null)
        } catch (error: Exception) {
            closeStream()
            GlobalState.log("Log export to $uri failed: $error")
            result.error("EXPORT_WRITE_FAILED", error.toString(), null)
        }
    }

    private fun renameDocument(call: MethodCall, result: Result) {
        val uri = call.argument<String>("uri")?.let(Uri::parse)
        val fileName = call.argument<String>("fileName")
        if (uri == null || fileName.isNullOrEmpty()) {
            result.error("EXPORT_BAD_REQUEST", "A destination URI and file name are required", null)
            return
        }
        val destination = runCatching {
            DocumentExportRules.destinationUri(GlobalState.application, uri, fileName)
        }.getOrDefault(uri)
        result.success(displayName(destination))
    }

    private fun displayName(uri: Uri): String? = runCatching {
        GlobalState.application.contentResolver
            .query(uri, null, null, null, null)?.use { cursor ->
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
            }
    }.getOrNull()

    private fun closeStream() {
        runCatching { stream?.flush() }
        runCatching { stream?.close() }
        stream = null
        streamUri = null
    }

    private fun resetDialog() {
        pendingResult = null
        pendingFileName = null
    }

    private fun reply(block: () -> Unit) = mainHandler.post(block)

    private companion object {
        const val REQUEST_CODE = 1004

        val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
    }
}
