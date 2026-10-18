import test from "node:test";
import assert from "node:assert/strict";
import { generateEncryptionKeyHex, encryptFilename, decryptFilename } from "./background/crypto.js";

test("generateEncryptionKeyHex creates 64-char hex key (256-bit)", () => {
  const key = generateEncryptionKeyHex();
  assert.equal(key.length, 64);
  assert.match(key, /^[0-9a-f]{64}$/);
});

test("encryptFilename and decryptFilename roundtrip matches original", async () => {
  const key = generateEncryptionKeyHex();
  const originalFilename = "fedora-workstation-40-x86_64.iso";

  const encrypted = await encryptFilename(originalFilename, key);
  assert.ok(encrypted.startsWith("enc:v1:"));
  assert.notEqual(encrypted, originalFilename);

  const decrypted = await decryptFilename(encrypted, key);
  assert.equal(decrypted, originalFilename);
});

test("decryptFilename returns plaintext unchanged if not encrypted", async () => {
  const key = generateEncryptionKeyHex();
  const plain = "archive.tar.gz";
  const result = await decryptFilename(plain, key);
  assert.equal(result, plain);
});

test("encryptFilename returns plaintext unchanged if key is missing", async () => {
  const plain = "archive.tar.gz";
  const result = await encryptFilename(plain, null);
  assert.equal(result, plain);
});
