package com.follow.clash.plugins

import org.junit.Assert.assertEquals
import org.junit.Test

/// The MIME type decides which provider the dialog opens.
class DocumentExportRulesTest {

    @Test
    fun `log archive is offered as a zip`() {
        assertEquals("application/zip", DocumentExportRules.mimeTypeFor("FlClash_logs_178.zip"))
        assertEquals("application/zip", DocumentExportRules.mimeTypeFor("FlClash_logs_178.ZIP"))
    }

    @Test
    fun `known text destinations keep their readable type`() {
        assertEquals("text/plain", DocumentExportRules.mimeTypeFor("core.log"))
        assertEquals("application/json", DocumentExportRules.mimeTypeFor("app-0001.jsonl"))
        assertEquals("text/yaml", DocumentExportRules.mimeTypeFor("config.yaml"))
    }

    @Test
    fun `an unknown extension falls back to the wildcard type`() {
        assertEquals("*/*", DocumentExportRules.mimeTypeFor("FlClash_logs"))
        assertEquals("*/*", DocumentExportRules.mimeTypeFor("export.bin"))
    }
}
