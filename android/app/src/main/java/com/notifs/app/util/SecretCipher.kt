package com.notifs.app.util

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Encrypts small secrets (filename key, device secret) before they are written to disk. */
interface SecretCipher {
    fun wrap(plain: String): String

    /** Returns null if [wrapped] cannot be authenticated (e.g. the Keystore key was wiped). */
    fun unwrap(wrapped: String): String?
}

/**
 * AES-256-GCM wrapping with a key from [keyProvider]. Format: `ks:v1:<b64 iv>:<b64 ct+tag>`.
 * The IV comes from the cipher itself (AndroidKeyStore requires randomized encryption).
 */
class AesGcmSecretCipher(private val keyProvider: () -> SecretKey) : SecretCipher {

    companion object {
        const val PREFIX = "ks:v1:"
        fun isWrapped(value: String) = value.startsWith(PREFIX)
    }

    override fun wrap(plain: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, keyProvider())
        val ct = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        val enc = Base64.getEncoder()
        return "$PREFIX${enc.encodeToString(cipher.iv)}:${enc.encodeToString(ct)}"
    }

    override fun unwrap(wrapped: String): String? {
        if (!isWrapped(wrapped)) return null
        return try {
            val parts = wrapped.removePrefix(PREFIX).split(":")
            require(parts.size == 2)
            val dec = Base64.getDecoder()
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, keyProvider(), GCMParameterSpec(128, dec.decode(parts[0])))
            String(cipher.doFinal(dec.decode(parts[1])), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }
}

/**
 * Non-exportable AES key held by the AndroidKeyStore (hardware-backed where available).
 * The raw key never enters app memory, so copying the DataStore file off the device (root,
 * adb backup on old builds, forensic image) does not reveal the secrets it wraps.
 */
object AndroidKeystoreKey {
    private const val ALIAS = "hmd_datastore_v1"
    private const val PROVIDER = "AndroidKeyStore"

    @Synchronized
    fun getOrCreate(): SecretKey {
        val keyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }
        (keyStore.getKey(ALIAS, null) as? SecretKey)?.let { return it }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }
}
