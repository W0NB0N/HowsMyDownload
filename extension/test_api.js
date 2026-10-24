/**
 * Tests for background/api.js: fail-closed encryption on the wire and secret-rotation races.
 */

import test, { beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installFakeChrome, installFakeFetch, sleep } from "./test_fake_chrome.js";
import { readFileSync } from "node:fs";
import { DEFAULT_SERVER_URL, prepareWirePayload, sendSample, resetBackoff } from "./background/api.js";
import { decryptFilename, generateEncryptionKeyHex } from "./background/crypto.js";

const KEY = generateEncryptionKeyHex();

function makeSample() {
  return {
    pairing_id: "p-1",
    source: "chrome",
    pc_name: "Desk",
    timestamp: new Date().toISOString(),
    downloads: [
      {
        id: "7",
        filename: "tax-return-2026.pdf",
        bytes_downloaded: 10,
        total_bytes: 100,
        state: "downloading",
        mime_type: "application/pdf"
      }
    ]
  };
}

function pairedStorage(overrides = {}) {
  return {
    enabled: true,
    serverUrl: "https://api.example",
    isPaired: true,
    pairingId: "p-1",
    pairingSecret: "secret-A",
    encryptionKey: KEY,
    ...overrides
  };
}

beforeEach(() => resetBackoff());

test("prepareWirePayload encrypts filename and mime_type without mutating the input", async () => {
  const sample = makeSample();
  const wire = await prepareWirePayload(sample, KEY);
  const [dl] = wire.downloads;

  assert.equal(sample.downloads[0].filename, "tax-return-2026.pdf");
  assert.ok(dl.filename.startsWith("enc:v1:"));
  assert.ok(dl.mime_type.startsWith("enc:v1:"));
  assert.equal(await decryptFilename(dl.filename, KEY), "tax-return-2026.pdf");
  assert.equal(await decryptFilename(dl.mime_type, KEY), "application/pdf");
  assert.equal(dl.bytes_downloaded, 10);
  assert.equal(dl.state, "downloading");
});

test("prepareWirePayload truncates very long names before encrypting", async () => {
  const sample = makeSample();
  sample.downloads[0].filename = "n".repeat(500) + ".iso";
  const wire = await prepareWirePayload(sample, KEY);
  const plain = await decryptFilename(wire.downloads[0].filename, KEY);
  assert.ok(plain.length <= 120 && plain.endsWith(".iso"));
});

test("prepareWirePayload refuses to run without a valid key", async () => {
  await assert.rejects(prepareWirePayload(makeSample(), null), /encryption key/);
  await assert.rejects(prepareWirePayload(makeSample(), "not-hex"), /encryption key/);
});

test("sendSample never puts plaintext filenames on the wire", async () => {
  installFakeChrome({ storage: pairedStorage() });
  const calls = installFakeFetch(() => ({ status: 200, body: { processed: 1 } }));

  await sendSample(makeSample());

  assert.equal(calls.length, 1);
  const { url, options } = calls[0];
  assert.equal(url, "https://api.example/v1/samples");
  assert.equal(options.headers.Authorization, "Bearer secret-A");
  assert.ok(!options.body.includes("tax-return"));
  assert.ok(!options.body.includes("application/pdf"));
});

test("sendSample drops the sample (fails closed) when paired without a key", async () => {
  const chromeState = installFakeChrome({ storage: pairedStorage({ encryptionKey: null }) });
  const calls = installFakeFetch(() => ({ status: 200 }));

  await sendSample(makeSample());

  assert.equal(calls.length, 0);
  assert.match(chromeState.store.lastServerError, /encryption key/);
  assert.equal(chromeState.store.isPaired, true);
});

test("sendSample does not contact the server when unpaired", async () => {
  installFakeChrome({ storage: pairedStorage({ isPaired: false, pairingSecret: null }) });
  const calls = installFakeFetch(() => ({ status: 200 }));
  await sendSample(makeSample());
  assert.equal(calls.length, 0);
});

test("a 401 caused by a concurrent secret rotation does not unpair; it retries", async () => {
  const chromeState = installFakeChrome({ storage: pairedStorage() });
  const calls = installFakeFetch((url, options, i) => {
    if (i === 0) {
      // Popup rotates the secret while this request is in flight
      chromeState.store.pairingSecret = "secret-B";
      return { status: 401 };
    }
    return { status: 200, body: { processed: 1 } };
  });

  await sendSample(makeSample());
  assert.equal(chromeState.store.isPaired, true);

  await sleep(120);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.headers.Authorization, "Bearer secret-B");
  assert.equal(chromeState.store.isPaired, true);
});

test("a 401 for the current secret means revoked: clear pairing and key", async () => {
  const chromeState = installFakeChrome({ storage: pairedStorage() });
  installFakeFetch(() => ({ status: 401 }));

  await sendSample(makeSample());

  assert.equal(chromeState.store.isPaired, false);
  assert.equal(chromeState.store.pairingSecret, null);
  assert.equal(chromeState.store.encryptionKey, null);
});

test("the popup and the background agree on the default server", () => {
  const popup = readFileSync(new URL("./popup/popup.js", import.meta.url), "utf8");
  const match = popup.match(/const DEFAULT_SERVER_URL = "([^"]+)";/);
  assert.ok(match, "popup.js defines DEFAULT_SERVER_URL");
  assert.equal(match[1], DEFAULT_SERVER_URL);
  assert.match(DEFAULT_SERVER_URL, /^https:\/\//);
});