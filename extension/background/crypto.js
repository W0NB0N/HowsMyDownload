/**
 * End-to-end Field-Level Encryption module for Download Notifs (AES-256-GCM).
 * Encrypts filenames on the client before dispatching to the server so that the server
 * never sees plaintext filenames. The encryption key is shared exclusively with the phone
 * via the QR code and never touches any server API.
 */

/**
 * Generates a cryptographically random 256-bit (32-byte) AES key as a 64-char hex string.
 * @returns {string} Hex-encoded 256-bit key
 */
export function generateEncryptionKeyHex() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Converts a hex string to a Uint8Array.
 * @param {string} hex 
 * @returns {Uint8Array}
 */
function hexToUint8Array(hex) {
  const matches = hex.match(/.{1,2}/g) || [];
  return new Uint8Array(matches.map(byte => parseInt(byte, 16)));
}

/**
 * Imports a raw hex key into a Web Crypto CryptoKey.
 * @param {string} hexKey 
 * @returns {Promise<CryptoKey>}
 */
async function importAesKey(hexKey) {
  const rawKey = hexToUint8Array(hexKey);
  return await crypto.subtle.importKey(
    "raw",
    rawKey,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"]
  );
}

/**
 * Encrypts a plaintext string using AES-256-GCM.
 * Output format: enc:v1:<base64-iv>:<base64-ciphertext-and-tag>
 * 
 * @param {string} plainText 
 * @param {string} hexKey 
 * @returns {Promise<string>}
 */
export async function encryptFilename(plainText, hexKey) {
  if (!hexKey || !plainText) {
    return plainText;
  }
  try {
    const key = await importAesKey(hexKey);
    const iv = crypto.getRandomValues(new Uint8Array(12)); // 96-bit standard IV
    const encoded = new TextEncoder().encode(plainText);

    const cipherBuffer = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv },
      key,
      encoded
    );

    const ivB64 = btoa(String.fromCharCode(...iv));
    const cipherB64 = btoa(String.fromCharCode(...new Uint8Array(cipherBuffer)));
    return `enc:v1:${ivB64}:${cipherB64}`;
  } catch (err) {
    console.error("[How's My Download] Crypto encryption error:", err);
    return plainText;
  }
}

/**
 * Decrypts a ciphertext string formatted as enc:v1:<base64-iv>:<base64-ciphertext-and-tag>.
 * 
 * @param {string} cipherText 
 * @param {string} hexKey 
 * @returns {Promise<string>}
 */
export async function decryptFilename(cipherText, hexKey) {
  if (!hexKey || !cipherText || !cipherText.startsWith("enc:v1:")) {
    return cipherText;
  }
  try {
    const parts = cipherText.split(":");
    if (parts.length !== 4) {
      return cipherText;
    }
    const iv = Uint8Array.from(atob(parts[2]), c => c.charCodeAt(0));
    const cipherBytes = Uint8Array.from(atob(parts[3]), c => c.charCodeAt(0));
    const key = await importAesKey(hexKey);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: iv },
      key,
      cipherBytes
    );

    return new TextDecoder().decode(decrypted);
  } catch (err) {
    console.error("[How's My Download] Crypto decryption error:", err);
    return cipherText;
  }
}
