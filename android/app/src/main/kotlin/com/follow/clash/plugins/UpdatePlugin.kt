package com.follow.clash.plugins

import android.app.Activity
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class UpdatePlugin : FlutterPlugin, ActivityAware, MethodChannel.MethodCallHandler {
    private lateinit var context: Context
    private lateinit var channel: MethodChannel
    private lateinit var scope: CoroutineScope
    private var activity: Activity? = null
    private val certificate = "4cc5094e24f4a4cfde3a37d6c839ae376bd74c50075d8ee6bc73e25682e9afad"

    private fun directory() = File(context.cacheDir, "app-updates").apply { mkdirs() }.canonicalFile

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
        channel = MethodChannel(binding.binaryMessenger, "com.follow.clash/update")
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "directory" -> result.success(directory().path)
            "canInstall" -> result.success(canInstall())
            "validate", "install" -> scope.launch {
                try {
                    val file = withContext(Dispatchers.IO) { validate(call) }
                    if (call.method == "validate") {
                        result.success(true)
                    } else {
                        val host = activity ?: error("No foreground activity")
                        if (!canInstall()) {
                            host.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:${context.packageName}")))
                            result.success("permission")
                        } else {
                            val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
                            val intent = Intent(Intent.ACTION_VIEW).apply {
                                setDataAndType(uri, "application/vnd.android.package-archive")
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                clipData = ClipData.newRawUri("FlClash update", uri)
                            }
                            host.startActivity(intent)
                            result.success("opened")
                        }
                    }
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    result.error("UPDATE_INVALID", error.message, null)
                }
            }
            else -> result.notImplemented()
        }
    }

    private fun canInstall() = Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
        context.packageManager.canRequestPackageInstalls()

    @Suppress("DEPRECATION")
    private fun validate(call: MethodCall): File {
        val file = File(requireNotNull(call.argument<String>("path"))).canonicalFile
        require(file.parentFile == directory() && Regex("release-[0-9]+\\.apk").matches(file.name))
        require(file.isFile && file.length() in 1..268435456L)
        val expectedHash = requireNotNull(call.argument<String>("sha256"))
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        require(hex(digest.digest()) == expectedHash)
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
            PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val archive = requireNotNull(context.packageManager.getPackageArchiveInfo(file.path, flags))
        val installed = context.packageManager.getPackageInfo(context.packageName, flags)
        require(archive.packageName == context.packageName)
        val expectedBuild = requireNotNull(call.argument<Number>("build")).toLong()
        require(version(archive) == expectedBuild && expectedBuild > version(installed))
        val signers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
            archive.signingInfo?.apkContentsSigners else archive.signatures
        require(signers != null && signers.size == 1)
        require(hex(MessageDigest.getInstance("SHA-256").digest(signers[0].toByteArray())) == certificate)
        return file
    }

    @Suppress("DEPRECATION")
    private fun version(info: PackageInfo) = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
        info.longVersionCode else info.versionCode.toLong()

    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it.toInt() and 255) }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        channel.setMethodCallHandler(null)
        scope.cancel()
    }
    override fun onAttachedToActivity(binding: ActivityPluginBinding) { activity = binding.activity }
    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) { activity = binding.activity }
    override fun onDetachedFromActivityForConfigChanges() { activity = null }
    override fun onDetachedFromActivity() { activity = null }
}
