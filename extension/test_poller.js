/**
 * Unit tests for background/poller.js: state mapping, filename extraction, schema conformance,
 * and the single-report pause behaviour. Imports the real module (no re-implementations).
 */

import test, { after } from "node:test";
import assert from "node:assert/strict";
import { installFakeChrome, installFakeFetch } from "./test_fake_chrome.js";
import {
  browserSource,
  extractFilename,
  mapDownloadState,
  toProtocolDownload,
  pollAndSample,
  rememberFinished,
  stopCommandWatch,
  stopPolling
} from "./background/poller.js";
import { generateEncryptionKeyHex } from "./background/crypto.js";

// A paired, idle poller with a paused download starts the command watch interval
after(() => {
  stopPolling();
  stopCommandWatch();
});

test("extractFilename handles Windows paths, POSIX paths, URLs and fallbacks", () => {
  assert.equal(
    extractFilename({ id: 1, filename: "C:\\Users\\Lenovo\\Downloads\\ubuntu-24.04.iso" }),
    "ubuntu-24.04.iso"
  );
  assert.equal(extractFilename({ id: 2, filename: "/home/user/archive.tar.gz" }), "archive.tar.gz");
  assert.equal(
    extractFilename({ id: 3, filename: "", url: "https://example.com/files/doc%20v2.pdf?token=1" }),
    "doc v2.pdf"
  );
  assert.equal(extractFilename({ id: 4, filename: "", url: "" }), "download-4");
  assert.equal(extractFilename({ id: 5, filename: "", url: "not a url" }), "download-5");
});

test("mapDownloadState maps Chrome states to protocol states", () => {
  const base = { state: "in_progress", bytesReceived: 1024, totalBytes: 2048, paused: false };
  assert.equal(mapDownloadState({ ...base, bytesReceived: 0, totalBytes: -1 }), "starting");
  assert.equal(mapDownloadState(base), "downloading");
  assert.equal(mapDownloadState({ ...base, paused: true }), "paused");
  assert.equal(mapDownloadState({ ...base, state: "complete" }), "completed");
  assert.equal(mapDownloadState({ ...base, state: "interrupted" }), "failed");
});

test("toProtocolDownload conforms to schema v1", () => {
  assert.deepEqual(
    toProtocolDownload({
      id: 42,
      filename: "D:\\Downloads\\large_game.zip",
      bytesReceived: 52428800,
      totalBytes: 104857600,
      state: "in_progress",
      paused: false,
      mime: "application/zip"
    }),
    {
      id: "42",
      filename: "large_game.zip",
      bytes_downloaded: 52428800,
      total_bytes: 104857600,
      state: "downloading",
      mime_type: "application/zip"
    }
  );

  const unknownSize = toProtocolDownload({
    id: 43, filename: "stream.mp4", bytesReceived: 1048576, totalBytes: -1, state: "in_progress"
  });
  assert.equal(unknownSize.total_bytes, null);
  assert.equal(unknownSize.bytes_downloaded, 1048576);
});

test("a paused download is reported once, then again only when it resumes", async () => {
  const download = {
    id: 99,
    filename: "C:\\dl\\file.iso",
    state: "in_progress",
    paused: true,
    bytesReceived: 500,
    totalBytes: 1000
  };
  installFakeChrome({
    downloads: [download],
    storage: {
      enabled: true,
      serverUrl: "https://api.example",
      isPaired: true,
      pairingId: "p-1",
      pairingSecret: "s",
      encryptionKey: generateEncryptionKeyHex()
    }
  });
  const calls = installFakeFetch(() => ({ status: 200, body: { processed: 1 } }));
  const sentStates = () => calls.map(c => JSON.parse(c.options.body).downloads[0].state);

  await pollAndSample();
  await pollAndSample();
  await pollAndSample();
  assert.deepEqual(sentStates(), ["paused"]);

  download.paused = false;
  download.bytesReceived = 600;
  await pollAndSample();
  assert.deepEqual(sentStates(), ["paused", "downloading"]);
});

test("a failed download that is resumed is not also reported as failed in the same sample", async () => {
  const download = {
    id: 77,
    filename: "C:\\dl\\big.iso",
    state: "interrupted",
    canResume: true,
    bytesReceived: 500,
    totalBytes: 1000
  };
  installFakeChrome({
    downloads: [download],
    storage: {
      enabled: true,
      serverUrl: "https://api.example",
      isPaired: true,
      pairingId: "p-1",
      pairingSecret: "s",
      encryptionKey: generateEncryptionKeyHex()
    }
  });
  const calls = installFakeFetch(() => ({ status: 200, body: { processed: 1 } }));

  await rememberFinished(77);
  // Resumed (e.g. from the phone) before the failure was ever sampled
  download.state = "in_progress";
  download.paused = false;
  download.bytesReceived = 600;
  await pollAndSample();

  const [sample] = calls.map(c => JSON.parse(c.options.body));
  assert.deepEqual(sample.downloads.filter(d => d.id === "77").map(d => d.state), ["downloading"]);
});

test("browserSource names the Chromium browser the phone should show", () => {
  const brands = (...names) => ({ userAgentData: { brands: names.map(brand => ({ brand, version: "1" })) } });
  assert.equal(browserSource(brands("Not.A/Brand", "Chromium", "Google Chrome")), "chrome");
  assert.equal(browserSource(brands("Chromium", "Microsoft Edge")), "edge");
  assert.equal(browserSource(brands("Chromium", "Brave")), "brave");
  assert.equal(browserSource({ brave: {}, userAgentData: { brands: [] } }), "brave");
  assert.equal(browserSource(brands("Chromium", "Opera")), "opera");
  assert.equal(browserSource(brands("Chromium")), "chromium");
  assert.equal(browserSource({}), "chromium");
  assert.equal(browserSource(undefined), "chromium");
});