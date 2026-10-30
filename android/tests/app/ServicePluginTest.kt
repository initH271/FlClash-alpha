package com.follow.clash.plugins

import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

private class RecordingResult : MethodChannel.Result {
    val replies = mutableListOf<Any?>()

    override fun success(result: Any?) {
        replies += result
    }

    override fun error(errorCode: String, errorMessage: String?, errorDetails: Any?) {
        replies += errorCode
    }

    override fun notImplemented() {
        replies += "notImplemented"
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class ServicePluginTest {
    // A restart sends start as soon as stop answers; the teardown must be over by then.
    @Test
    fun stopAnswersOnlyAfterTheTeardownSettles() = runTest(UnconfinedTestDispatcher()) {
        val teardown = CompletableDeferred<Boolean>()
        val result = RecordingResult()

        launch { replyWhenSettled(teardown, result) }
        assertTrue(result.replies.isEmpty())

        teardown.complete(true)
        assertEquals(listOf<Any?>(true), result.replies)
    }

    @Test
    fun aSupersededStopStillAnswers() = runTest(UnconfinedTestDispatcher()) {
        val teardown = CompletableDeferred<Boolean>()
        val result = RecordingResult()

        launch { replyWhenSettled(teardown, result) }
        teardown.complete(false)

        assertEquals(listOf<Any?>(true), result.replies)
    }
}
