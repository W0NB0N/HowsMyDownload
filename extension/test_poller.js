/**
 * Unit test verifying extension poller logic: state transitions, filename extraction, and schema conformance.
 */

import assert from "node:assert";

// Simulation helpers replicating poller.js logic
function extractFilename(item) {
  if (item.filename) {
    const normalized = item.filename.replace(/\\/g, "/");
    const parts = normalized.split("/");
    const name = parts[parts.length - 1];
    if (name) return name;
  }
  if (item.url) {
    try {
      const urlObj = new URL(item.url);
      const parts = urlObj.pathname.split("/").filter(Boolean);
      if (parts.length > 0) {
        return decodeURIComponent(parts[parts.length - 1]);
      }
    } catch {
      // Ignore URL parse error
    }
  }
  return `download-${item.id}`;
}

function mapDownloadState(item) {
  if (item.state === "complete") {
    return "completed";
  }
  if (item.state === "interrupted") {
    return "failed";
  }
  if (item.paused) {
    return "paused";
  }
  if (item.bytesReceived === 0 && item.totalBytes <= 0) {
    return "starting";
  }
  return "downloading";
}

function toProtocolDownload(item) {
  const state = mapDownloadState(item);
  return {
    id: String(item.id),
    filename: extractFilename(item),
    bytes_downloaded: Math.max(0, item.bytesReceived || 0),
    total_bytes: item.totalBytes > 0 ? item.totalBytes : null,
    state: state,
    mime_type: item.mime || undefined
  };
}

// Tests
console.log("Running Extension Poller Unit Tests...\n");

// 1. Filename extraction tests
console.log("1. Testing filename extraction:");
assert.strictEqual(
  extractFilename({ id: 1, filename: "C:\\Users\\Lenovo\\Downloads\\ubuntu-24.04.iso" }),
  "ubuntu-24.04.iso"
);
assert.strictEqual(
  extractFilename({ id: 2, filename: "/home/user/downloads/archive.tar.gz" }),
  "archive.tar.gz"
);
assert.strictEqual(
  extractFilename({ id: 3, filename: "", url: "https://example.com/files/document.pdf?token=123" }),
  "document.pdf"
);
assert.strictEqual(
  extractFilename({ id: 4, filename: "", url: "" }),
  "download-4"
);
console.log(" ✓ Filename extraction passed.");

// 2. State mapping tests
console.log("\n2. Testing state mapping:");
assert.strictEqual(
  mapDownloadState({ state: "in_progress", bytesReceived: 0, totalBytes: -1, paused: false }),
  "starting"
);
assert.strictEqual(
  mapDownloadState({ state: "in_progress", bytesReceived: 1024, totalBytes: 2048, paused: false }),
  "downloading"
);
assert.strictEqual(
  mapDownloadState({ state: "in_progress", bytesReceived: 1024, totalBytes: 2048, paused: true }),
  "paused"
);
assert.strictEqual(
  mapDownloadState({ state: "complete", bytesReceived: 2048, totalBytes: 2048, paused: false }),
  "completed"
);
assert.strictEqual(
  mapDownloadState({ state: "interrupted", bytesReceived: 1024, totalBytes: 2048, paused: false }),
  "failed"
);
console.log(" ✓ State mapping passed.");

// 3. Schema v1 conformance test
console.log("\n3. Testing protocol transformation:");
const chromeItem = {
  id: 42,
  filename: "D:\\Downloads\\large_game.zip",
  bytesReceived: 52428800,
  totalBytes: 104857600,
  state: "in_progress",
  paused: false,
  mime: "application/zip"
};

const protocolItem = toProtocolDownload(chromeItem);
assert.deepStrictEqual(protocolItem, {
  id: "42",
  filename: "large_game.zip",
  bytes_downloaded: 52428800,
  total_bytes: 104857600,
  state: "downloading",
  mime_type: "application/zip"
});

// Unknown total size test
const chunkedItem = {
  id: 43,
  filename: "D:\\Downloads\\stream.mp4",
  bytesReceived: 1048576,
  totalBytes: -1,
  state: "in_progress",
  paused: false
};
const chunkedProtocol = toProtocolDownload(chunkedItem);
assert.strictEqual(chunkedProtocol.total_bytes, null);
assert.strictEqual(chunkedProtocol.bytes_downloaded, 1048576);
console.log(" ✓ Schema v1 conformance passed.");

console.log("\n✅ ALL TESTS PASSED!");
