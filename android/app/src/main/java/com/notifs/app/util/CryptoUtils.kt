package com.notifs.app.util

import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Client-side cryptographic utility implementing AES-256-GCM decryption for filenames.
 * Encrypted strings are formatted as: enc:v1:<base64-iv>:<base64-ciphertext-and-tag>
 * (produced by extension/background/crypto.js).
 */
object CryptoUtils {
    private const val PREFIX = "enc:v1:"
    private val KEY_HEX = Regex("^[0-9a-fA-F]{64}$")

    /** Shown when a name is encrypted but cannot be decrypted (no key, wrong key, tampered). */
    const val ENCRYPTED_PLACEHOLDER = "Encrypted file"

    fun isValidKeyHex(hexKey: String?): Boolean = hexKey != null && KEY_HEX.matches(hexKey)

    fun hexToBytes(hex: String): ByteArray {
        require(hex.length % 2 == 0) { "Hex string must have an even length" }
        val data = ByteArray(hex.length / 2)
        var i = 0
        while (i < hex.length) {
            val hi = Character.digit(hex[i], 16)
            val lo = Character.digit(hex[i + 1], 16)
            require(hi >= 0 && lo >= 0) { "Invalid hex character" }
            data[i / 2] = ((hi shl 4) + lo).toByte()
            i += 2
        }
        return data
    }

    /**
     * Encrypts a plaintext filename using AES-256-GCM (used by tests to mirror the extension).
     * Throws on an invalid key instead of ever returning plaintext.
     */
    fun encryptFilename(plainText: String, hexKey: String?): String {
        require(isValidKeyHex(hexKey)) { "Invalid or missing encryption key" }
        val iv = ByteArray(12)
        java.security.SecureRandom().nextBytes(iv)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(hexToBytes(hexKey!!), "AES"), GCMParameterSpec(128, iv))
        val cipherAndTag = cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))

        val encoder = Base64.getEncoder()
        return "$PREFIX${encoder.encodeToString(iv)}:${encoder.encodeToString(cipherAndTag)}"
    }

    /**
     * Decrypts an AES-256-GCM encrypted filename using the stored hex key.
     * Plain (unencrypted) strings pass through unchanged. Encrypted strings that cannot be
     * authenticated return [ENCRYPTED_PLACEHOLDER] so ciphertext is never shown to the user.
     */
    fun decryptFilename(encryptedStr: String, hexKey: String?): String {
        if (!encryptedStr.startsWith(PREFIX)) {
            return encryptedStr
        }
        if (!isValidKeyHex(hexKey)) {
            return ENCRYPTED_PLACEHOLDER
        }

        return try {
            val parts = encryptedStr.split(":")
            require(parts.size == 4) { "Malformed ciphertext" }
            val decoder = Base64.getDecoder()
            val iv = decoder.decode(parts[2])
            val cipherAndTag = decoder.decode(parts[3])

            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(hexToBytes(hexKey!!), "AES"), GCMParameterSpec(128, iv))
            String(cipher.doFinal(cipherAndTag), Charsets.UTF_8)
        } catch (_: Exception) {
            ENCRYPTED_PLACEHOLDER
        }
    }
}
