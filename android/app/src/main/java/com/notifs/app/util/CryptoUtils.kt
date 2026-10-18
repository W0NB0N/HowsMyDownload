package com.notifs.app.util

import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Client-side cryptographic utility implementing AES-256-GCM decryption for filenames.
 * Encrypted strings are formatted as: enc:v1:<base64-iv>:<base64-ciphertext-and-tag>
 */
object CryptoUtils {
    private const val TAG = "CryptoUtils"
    private const val PREFIX = "enc:v1:"

    fun hexToBytes(hex: String): ByteArray {
        val len = hex.length
        val data = ByteArray(len / 2)
        var i = 0
        while (i < len) {
            data[i / 2] = ((Character.digit(hex[i], 16) shl 4) + Character.digit(hex[i + 1], 16)).toByte()
            i += 2
        }
        return data
    }

    /**
     * Encrypts a plaintext filename using AES-256-GCM.
     * Output format: enc:v1:<base64-iv>:<base64-ciphertext-and-tag>
     */
    fun encryptFilename(plainText: String, hexKey: String?): String {
        if (hexKey.isNullOrBlank()) return plainText
        try {
            val iv = ByteArray(12)
            java.security.SecureRandom().nextBytes(iv)
            val keyBytes = hexToBytes(hexKey)
            val secretKey = SecretKeySpec(keyBytes, "AES")
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            val spec = GCMParameterSpec(128, iv)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey, spec)
            val cipherAndTag = cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))

            val ivB64 = Base64.getEncoder().encodeToString(iv)
            val cipherB64 = Base64.getEncoder().encodeToString(cipherAndTag)
            return "$PREFIX$ivB64:$cipherB64"
        } catch (_: Exception) {
            return plainText
        }
    }

    /**
     * Decrypts an AES-256-GCM encrypted filename using the stored hex key.
     * If the string is not encrypted (e.g. legacy/plain), returns it unaltered.
     */
    fun decryptFilename(encryptedStr: String, hexKey: String?): String {
        if (hexKey.isNullOrBlank() || !encryptedStr.startsWith(PREFIX)) {
            return encryptedStr
        }

        try {
            val parts = encryptedStr.split(":")
            if (parts.size != 4) {
                return encryptedStr
            }

            val iv = Base64.getDecoder().decode(parts[2])
            val cipherAndTag = Base64.getDecoder().decode(parts[3])
            val keyBytes = hexToBytes(hexKey)

            val secretKey = SecretKeySpec(keyBytes, "AES")
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            val spec = GCMParameterSpec(128, iv)
            cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)

            val decrypted = cipher.doFinal(cipherAndTag)
            return String(decrypted, Charsets.UTF_8)
        } catch (_: Exception) {
            return encryptedStr
        }
    }
}
