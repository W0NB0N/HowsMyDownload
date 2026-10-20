package com.notifs.app.util

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Same wrapping code as production; a JVM AES key stands in for the AndroidKeyStore key. */
class SecretCipherTest {

    private fun newKey(): SecretKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    private val key = newKey()
    private val cipher = AesGcmSecretCipher { key }

    @Test
    fun roundtrip() {
        val secret = "0123456789abcdef".repeat(4)
        val wrapped = cipher.wrap(secret)
        assertTrue(AesGcmSecretCipher.isWrapped(wrapped))
        assertFalse("plaintext must not appear in the stored value", wrapped.contains(secret))
        assertEquals(secret, cipher.unwrap(wrapped))
    }

    @Test
    fun freshIvEachTime() {
        assertNotEquals(cipher.wrap("same"), cipher.wrap("same"))
    }

    @Test
    fun wrongKeyOrTamperingReturnsNull() {
        val wrapped = cipher.wrap("device-secret")
        assertNull(AesGcmSecretCipher { newKey() }.unwrap(wrapped))

        val last = wrapped.last()
        val tampered = wrapped.dropLast(1) + (if (last == 'A') 'B' else 'A')
        assertNull(cipher.unwrap(tampered))
        assertNull(cipher.unwrap("ks:v1:garbage"))
    }

    @Test
    fun plaintextLegacyValuesAreNotTreatedAsWrapped() {
        assertFalse(AesGcmSecretCipher.isWrapped("legacy-plain-secret"))
        assertNull(cipher.unwrap("legacy-plain-secret"))
    }
}
