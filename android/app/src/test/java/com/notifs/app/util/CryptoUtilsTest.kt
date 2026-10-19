package com.notifs.app.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CryptoUtilsTest {

    private val testKey = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    private val otherKey = "f".repeat(64)

    @Test
    fun testEncryptionAndDecryptionRoundtrip() {
        val originalFilename = "ubuntu-24.04-desktop-amd64.iso"
        val encrypted = CryptoUtils.encryptFilename(originalFilename, testKey)

        assertTrue("Encrypted string should have enc:v1: prefix", encrypted.startsWith("enc:v1:"))
        assertNotEquals("Encrypted string must not match original", originalFilename, encrypted)

        val decrypted = CryptoUtils.decryptFilename(encrypted, testKey)
        assertEquals("Decrypted filename must match original", originalFilename, decrypted)
    }

    /** Ciphertexts produced by extension/background/crypto.js (Web Crypto) with testKey. */
    @Test
    fun testDecryptsCiphertextFromTheExtension() {
        assertEquals(
            "ubuntu-24.04-desktop-amd64.iso",
            CryptoUtils.decryptFilename(
                "enc:v1:2/DBukjCy9ztZRJO:2JVFm0lRIE4pQS1uL13NHg4TKR28x8lpPm7Vv8xp7bCLmNTzEMrdsxnQmuJPuQ==",
                testKey
            )
        )
        assertEquals(
            "отчёт 📦.zip",
            CryptoUtils.decryptFilename(
                "enc:v1:FX0AdjHgc2cSI7AI:TSTld2BUQwYiFif+6foUPU1rZkuHX4rU97m1nENvTAnqogs=",
                testKey
            )
        )
    }

    @Test
    fun testPlaintextFallbackWhenNotEncrypted() {
        val plain = "regular_download.zip"
        assertEquals("Unencrypted string should pass through unchanged", plain, CryptoUtils.decryptFilename(plain, testKey))
    }

    @Test
    fun testMissingKeyShowsPlaceholderNotCiphertext() {
        val encrypted = CryptoUtils.encryptFilename("document.pdf", testKey)

        assertEquals(CryptoUtils.ENCRYPTED_PLACEHOLDER, CryptoUtils.decryptFilename(encrypted, null))
        assertEquals(CryptoUtils.ENCRYPTED_PLACEHOLDER, CryptoUtils.decryptFilename(encrypted, "   "))
        assertEquals(CryptoUtils.ENCRYPTED_PLACEHOLDER, CryptoUtils.decryptFilename(encrypted, "abc"))
    }

    @Test
    fun testWrongKeyOrTamperingIsRejected() {
        val encrypted = CryptoUtils.encryptFilename("payslip.pdf", testKey)
        assertEquals(CryptoUtils.ENCRYPTED_PLACEHOLDER, CryptoUtils.decryptFilename(encrypted, otherKey))

        val parts = encrypted.split(":")
        val ct = parts[3]
        val flipped = (if (ct[0] == 'A') 'B' else 'A') + ct.substring(1)
        val tampered = "enc:v1:${parts[2]}:$flipped"
        assertEquals(CryptoUtils.ENCRYPTED_PLACEHOLDER, CryptoUtils.decryptFilename(tampered, testKey))
        assertEquals(CryptoUtils.ENCRYPTED_PLACEHOLDER, CryptoUtils.decryptFilename("enc:v1:garbage", testKey))
    }

    @Test
    fun testEncryptRefusesInvalidKey() {
        assertThrows(IllegalArgumentException::class.java) { CryptoUtils.encryptFilename("a.iso", null) }
        assertThrows(IllegalArgumentException::class.java) { CryptoUtils.encryptFilename("a.iso", "zz".repeat(32)) }
    }

    @Test
    fun testKeyValidation() {
        assertTrue(CryptoUtils.isValidKeyHex(testKey))
        assertTrue(CryptoUtils.isValidKeyHex(testKey.uppercase()))
        assertFalse(CryptoUtils.isValidKeyHex(testKey.dropLast(2)))
        assertFalse(CryptoUtils.isValidKeyHex("g".repeat(64)))
        assertFalse(CryptoUtils.isValidKeyHex(null))
    }

    @Test
    fun testHexToBytesConversion() {
        val bytes = CryptoUtils.hexToBytes("00ff10a5")
        assertEquals(4, bytes.size)
        assertEquals(0.toByte(), bytes[0])
        assertEquals((-1).toByte(), bytes[1]) // 0xff is -1 as signed byte
        assertEquals(0x10.toByte(), bytes[2])
        assertEquals(0xa5.toByte(), bytes[3])
        assertThrows(IllegalArgumentException::class.java) { CryptoUtils.hexToBytes("abc") }
    }
}
