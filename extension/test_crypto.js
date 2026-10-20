import test from "node:test";
import assert from "node:assert/strict";
import {
  generateEncryptionKeyHex,
  encryptField,
  encryptFilename,
  decryptFilename,
  isValidKeyHex,
  truncateFilename,
  MAX_FILENAME_CHARS
} from "./background/crypto.js";

test("generateEncryptionKeyHex creates 64-char hex key (256-bit)", () => {
  const key = generateEncryptionKeyHex();
  assert.equal(key.length, 64);
  assert.match(key, /^[0-9a-f]{64}$/);
  assert.notEqual(key, generateEncryptionKeyHex());
});

test("encryptFilename and decryptFilename roundtrip matches original", async () => {
  const key = generateEncryptionKeyHex();
  const originalFilename = "fedora-workstation-40-x86_64.iso";

  const encrypted = await encryptFilename(originalFilename, key);
  assert.ok(encrypted.startsWith("enc:v1:"));
  assert.ok(!encrypted.includes("fedora"));

  assert.equal(await decryptFilename(encrypted, key), originalFilename);
});

test("unicode filenames roundtrip", async () => {
  const key = generateEncryptionKeyHex();
  const name = "отчёт 📦 データ.zip";
  assert.equal(await decryptFilename(await encryptField(name, key), key), name);
});

test("each encryption uses a fresh IV", async () => {
  const key = generateEncryptionKeyHex();
  const a = await encryptField("same.iso", key);
  const b = await encryptField("same.iso", key);
  assert.notEqual(a, b);
  assert.notEqual(a.split(":")[2], b.split(":")[2]);
});

test("encryption fails closed: missing or malformed key throws, never returns plaintext", async () => {
  for (const badKey of [null, undefined, "", "abc", "zz".repeat(32), "a".repeat(63)]) {
    await assert.rejects(encryptField("secret-plans.pdf", badKey), /encryption key/);
  }
  await assert.rejects(encryptField(42, generateEncryptionKeyHex()), TypeError);
});

test("tampered ciphertext or wrong key is rejected by GCM authentication", async () => {
  const key = generateEncryptionKeyHex();
  const encrypted = await encryptField("bank-statement.pdf", key);
  const [, , iv, ct] = encrypted.split(":");
  const flipped = (ct[0] === "A" ? "B" : "A") + ct.slice(1);

  await assert.rejects(decryptFilename(`enc:v1:${iv}:${flipped}`, key));
  await assert.rejects(decryptFilename(encrypted, generateEncryptionKeyHex()));
});

test("decryptFilename returns plaintext unchanged if not encrypted", async () => {
  const plain = "archive.tar.gz";
  assert.equal(await decryptFilename(plain, generateEncryptionKeyHex()), plain);
});

test("isValidKeyHex accepts only 256-bit hex keys", () => {
  assert.equal(isValidKeyHex("ab".repeat(32)), true);
  assert.equal(isValidKeyHex("AB".repeat(32)), true);
  assert.equal(isValidKeyHex("ab".repeat(16)), false);
  assert.equal(isValidKeyHex(null), false);
});

test("truncateFilename bounds length and keeps the extension", () => {
  assert.equal(truncateFilename("short.iso"), "short.iso");

  const long = "x".repeat(300) + ".tar.gz";
  const cut = truncateFilename(long);
  assert.equal(Array.from(cut).length, MAX_FILENAME_CHARS);
  assert.ok(cut.endsWith("….gz"));

  const noExt = truncateFilename("y".repeat(200));
  assert.equal(Array.from(noExt).length, MAX_FILENAME_CHARS);
});

test("truncateFilename never splits surrogate pairs", () => {
  const cut = truncateFilename("📦".repeat(200) + ".zip");
  assert.doesNotThrow(() => encodeURIComponent(cut));
  assert.ok(cut.endsWith(".zip"));
});
