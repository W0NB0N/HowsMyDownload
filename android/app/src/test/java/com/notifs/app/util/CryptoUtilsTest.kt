package com.notifs.app.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CryptoUtilsTest {

    private val testKey = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    @Test
    fun testEncryptionAndDecryptionRoundtrip() {
        val originalFilename = "ubuntu-24.04-desktop-amd64.iso"
        val encrypted = CryptoUtils.encryptFilename(originalFilename, testKey)

        assertTrue("Encrypted string should have enc:v1: prefix", encrypted.startsWith("enc:v1:"))
        assertNotEquals("Encrypted string must not match original", originalFilename, encrypted)

        val decrypted = CryptoUtils.decryptFilename(encrypted, testKey)
        assertEquals("Decrypted filename must match original", originalFilename, decrypted)
    }

    @Test
    fun testPlaintextFallbackWhenNotEncrypted() {
        val plain = "regular_download.zip"
        val result = CryptoUtils.decryptFilename(plain, testKey)
        assertEquals("Unencrypted string should pass through unchanged", plain, result)
    }

    @Test
    fun testDecryptionWithNullOrBlankKeyReturnsRaw() {
        val original = "document.pdf"
        val encrypted = CryptoUtils.encryptFilename(original, testKey)

        val resultNullKey = CryptoUtils.decryptFilename(encrypted, null)
        assertEquals("With null key, raw encrypted string should be returned", encrypted, resultNullKey)

        val resultBlankKey = CryptoUtils.decryptFilename(encrypted, "   ")
        assertEquals("With blank key, raw encrypted string should be returned", encrypted, resultBlankKey)
    }

    @Test
    fun testHexToBytesConversion() {
        val hex = "00ff10a5"
        val bytes = CryptoUtils.hexToBytes(hex)
        assertEquals(4, bytes.size)
        assertEquals(0.toByte(), bytes[0])
        assertEquals((-1).toByte(), bytes[1]) // 0xff is -1 as signed byte
        assertEquals(0x10.toByte(), bytes[2])
        assertEquals(0xa5.toByte(), bytes[3])
    }
}
