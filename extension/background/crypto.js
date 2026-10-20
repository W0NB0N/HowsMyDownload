/**
 * End-to-end Field-Level Encryption module for Download Notifs (AES-256-GCM).
 * Encrypts filenames (and MIME types) on the client before dispatching to the server so that
 * the server never sees them. The encryption key is shared exclusively with the phone via the
 * QR code and never touches any server API.
 *
 * Encryption fails closed: any problem throws instead of returning plaintext, so a bug or a
 * missing key can never leak a filename to the server.
 */

const KEY_HEX_PATTERN = /^[0-9a-f]{64}$/i;
const ENC_PREFIX = "enc:v1:";

// Bounds the ciphertext so a single download stays small inside the 4KB FCM data payload.
export const MAX_FILENAME_CHARS = 120;

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
 * @param {unknown} hexKey
 * @returns {boolean} true if hexKey is a 64-char hex string (256-bit key)
 */
export function isValidKeyHex(hexKey) {
  return typeof hexKey === "string" && KEY_HEX_PATTERN.test(hexKey);
}

/**
 * Shortens long filenames to MAX_FILENAME_CHARS, keeping the extension visible.
 * "a-very-long-name….iso"
 * @param {string} name
 * @param {number} maxChars
 * @returns {string}
 */
export function truncateFilename(name, maxChars = MAX_FILENAME_CHARS) {
  const chars = Array.from(name); // code points, so surrogate pairs are never split
  if (chars.length <= maxChars) {
    return name;
  }
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? Array.from(name.slice(dot)) : [];
  const keepExt = ext.length > 0 && ext.length <= 10 ? ext : [];
  const head = chars.slice(0, maxChars - keepExt.length - 1);
  return head.join("") + "…" + keepExt.join("");
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
  return await crypto.subtle.importKey(
    "raw",
    hexToUint8Array(hexKey),
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"]
  );
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const b of bytes) {
    binary += String.fromCharCode(b);
  }
  return btoa(binary);
}

/**
 * Encrypts a string field using AES-256-GCM with a fresh random 96-bit IV.
 * Output format: enc:v1:<base64-iv>:<base64-ciphertext-and-tag>
 *
 * @param {string} plainText
 * @param {string} hexKey
 * @returns {Promise<string>}
 * @throws if the key is invalid or encryption fails (never returns plaintext)
 */
export async function encryptField(plainText, hexKey) {
  if (!isValidKeyHex(hexKey)) {
    throw new Error("Invalid or missing encryption key");
  }
  if (typeof plainText !== "string") {
    throw new TypeError("encryptField expects a string");
  }

  const key = await importAesKey(hexKey);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const cipherBuffer = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv },
    key,
    new TextEncoder().encode(plainText)
  );

  return `${ENC_PREFIX}${bytesToBase64(iv)}:${bytesToBase64(new Uint8Array(cipherBuffer))}`;
}

export const encryptFilename = encryptField;

/**
 * Decrypts a ciphertext string formatted as enc:v1:<base64-iv>:<base64-ciphertext-and-tag>.
 * Non-encrypted input is returned unchanged; tampered input or a wrong key throws.
 *
 * @param {string} cipherText
 * @param {string} hexKey
 * @returns {Promise<string>}
 */
export async function decryptFilename(cipherText, hexKey) {
  if (!cipherText || !cipherText.startsWith(ENC_PREFIX)) {
    return cipherText;
  }
  if (!isValidKeyHex(hexKey)) {
    throw new Error("Invalid or missing encryption key");
  }
  const parts = cipherText.split(":");
  if (parts.length !== 4) {
    throw new Error("Malformed ciphertext");
  }
  const iv = Uint8Array.from(atob(parts[2]), c => c.charCodeAt(0));
  const cipherBytes = Uint8Array.from(atob(parts[3]), c => c.charCodeAt(0));
  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: iv },
    await importAesKey(hexKey),
    cipherBytes
  );
  return new TextDecoder().decode(decrypted);
}
