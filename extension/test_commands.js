/**
 * Tests for phone commands: background/commands.js (execution and validation), the command
 * plumbing in api.js, and the poller's command watch / restart bookkeeping.
 */

import test, { afterEach, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installFakeChrome, installFakeFetch, sleep } from "./test_fake_chrome.js";
import { handleCommands, isValidCommand } from "./background/commands.js";
import { fetchCommands, resetBackoff, sendSample, setCommandHandler } from "./background/api.js";
import {
  pollAndSample,
  stopCommandWatch,
  stopPolling,
  updateCommandWatch
} from "./background/poller.js";
import { generateEncryptionKeyHex } from "./background/crypto.js";

const KEY = generateEncryptionKeyHex();
let nextCommand = 0;

function command(action, downloadId) {
  nextCommand++;
  return {
    command_id: nextCommand.toString(16).padStart(32, "0"),
    download_id: String(downloadId),
    action,
    issued_at: new Date().toISOString()
  };
}

function setup(downloads, storageOverrides = {}) {
  const chromeState = installFakeChrome({
    downloads,
    storage: {
      enabled: true,
      serverUrl: "https://api.example",
      isPaired: true,
      pairingId: "p-1",
      pairingSecret: "secret-A",
      encryptionKey: KEY,
      ...storageOverrides
    }
  });
  const calls = installFakeFetch(() => ({ status: 200, body: { processed: 1, commands: [] } }));
  return { chromeState, calls };
}

const samples = calls => calls
  .filter(c => c.url.endsWith("/v1/samples"))
  .map(c => JSON.parse(c.options.body));

const results = calls => calls
  .filter(c => c.url.includes("/result"))
  .map(c => ({ url: c.url, ...JSON.parse(c.options.body) }));

function running(id, extra = {}) {
  return {
    id, url: `https://cdn.example/file-${id}.iso`, filename: `C:\\dl\\file-${id}.iso`,
    state: "in_progress", paused: false, bytesReceived: 500, totalBytes: 1000, ...extra
  };
}

beforeEach(() => resetBackoff());

afterEach(async () => {
  // Let the immediate sample a command triggers finish, then stop the intervals it started
  await sleep(20);
  if (globalThis.chrome) {
    stopPolling();
    stopCommandWatch();
  }
});

test("isValidCommand accepts only well-formed commands", () => {
  assert.ok(isValidCommand(command("pause", 1)));
  assert.ok(!isValidCommand(null));
  assert.ok(!isValidCommand({ ...command("pause", 1), action: "erase" }));
  assert.ok(!isValidCommand({ ...command("pause", 1), download_id: "1; rm" }));
  assert.ok(!isValidCommand({ ...command("pause", 1), download_id: 1 }));
  assert.ok(!isValidCommand({ ...command("pause", 1), command_id: "short" }));
});

test("pause pauses a running download and the phone gets a fresh sample", async () => {
  const dl = running(1);
  const { chromeState, calls } = setup([dl]);

  await handleCommands([command("pause", 1)]);
  await sleep(30);

  assert.deepEqual(chromeState.downloadCalls, [["pause", 1]]);
  assert.equal(dl.paused, true);
  const last = samples(calls).at(-1);
  assert.equal(last.downloads.find(d => d.id === "1").state, "paused");
  assert.deepEqual(results(calls), []);
});

test("pausing an already paused download is a no-op, not an error", async () => {
  const { chromeState, calls } = setup([running(2, { paused: true })]);
  await handleCommands([command("pause", 2)]);
  assert.deepEqual(chromeState.downloadCalls, []);
  assert.deepEqual(results(calls), []);
});

test("resume resumes a paused download", async () => {
  const dl = running(3, { paused: true });
  const { chromeState } = setup([dl]);
  await handleCommands([command("resume", 3)]);
  assert.deepEqual(chromeState.downloadCalls, [["resume", 3]]);
  assert.equal(dl.paused, false);
});

test("resume of a failed download works only when Chrome can resume it", async () => {
  const resumable = running(4, { state: "interrupted", canResume: true });
  const dead = running(5, { state: "interrupted", canResume: false });
  const { chromeState, calls } = setup([resumable, dead]);

  const failing = command("resume", 5);
  await handleCommands([command("resume", 4), failing]);

  assert.deepEqual(chromeState.downloadCalls, [["resume", 4]]);
  assert.equal(resumable.state, "in_progress");
  assert.deepEqual(results(calls), [{
    url: `https://api.example/v1/pairings/p-1/commands/${failing.command_id}/result`,
    download_id: "5",
    action: "resume",
    ok: false,
    error: "not_resumable"
  }]);
  const reportCall = calls.find(c => c.url.includes("/result"));
  assert.equal(reportCall.options.headers.Authorization, "Bearer secret-A");
});

test("commands for unknown downloads or wrong states are reported, not executed", async () => {
  const { chromeState, calls } = setup([running(6, { state: "complete" })]);
  await handleCommands([command("pause", 999), command("pause", 6), command("restart", 6)]);
  assert.deepEqual(chromeState.downloadCalls, []);
  assert.deepEqual(results(calls).map(r => r.error), ["not_found", "invalid_state", "invalid_state"]);
});

test("restart cancels, re-downloads the original URL and reports the old id as erased", async () => {
  const dl = running(7, { url: "https://origin.example/get?id=7", finalUrl: "https://cdn.example/signed" });
  const { chromeState, calls } = setup([dl]);

  await handleCommands([command("restart", 7)]);
  await sleep(30);

  assert.deepEqual(chromeState.downloadCalls, [
    ["cancel", 7],
    ["download", { url: "https://origin.example/get?id=7", saveAs: false }],
    ["erase", { id: 7 }]
  ]);
  const reported = samples(calls).flatMap(s => s.downloads);
  const old = reported.filter(d => d.id === "7");
  assert.deepEqual(old.map(d => d.state), ["erased"]); // never shown as "failed"
  assert.ok(reported.some(d => d.id === "1000" && d.state === "starting"));
  assert.deepEqual(results(calls), []);

  // Reported as erased only once
  await pollAndSample();
  assert.equal(samples(calls).flatMap(s => s.downloads).filter(d => d.id === "7").length, 1);
});

test("restart of a failed download does not cancel it first", async () => {
  const { chromeState } = setup([running(8, { state: "interrupted", canResume: false })]);
  await handleCommands([command("restart", 8)]);
  assert.deepEqual(chromeState.downloadCalls.map(c => c[0]), ["download", "erase"]);
});

test("restart refuses URLs that cannot be fetched again", async () => {
  const { chromeState, calls } = setup([
    running(9, { url: "blob:https://app.example/123", finalUrl: "blob:https://app.example/123" })
  ]);
  await handleCommands([command("restart", 9)]);
  assert.deepEqual(chromeState.downloadCalls, []);
  assert.equal(results(calls)[0].error, "unsupported_url");
});

test("a restart that fails after cancelling reports the error and the download as failed", async () => {
  const { chromeState, calls } = setup([running(10)]);
  chromeState.failNextDownload = true;

  await handleCommands([command("restart", 10)]);
  await sleep(30);

  assert.equal(results(calls)[0].error, "browser_error");
  const states = samples(calls).flatMap(s => s.downloads).filter(d => d.id === "10").map(d => d.state);
  assert.ok(states.includes("failed"));
  assert.ok(!states.includes("erased"));
});

test("the same command delivered twice runs once; malformed commands are ignored", async () => {
  const { chromeState } = setup([running(11)]);
  const cmd = command("pause", 11);
  await handleCommands([cmd, { ...cmd }, { action: "pause", download_id: "11" }]);
  await handleCommands([cmd]);
  assert.deepEqual(chromeState.downloadCalls, [["pause", 11]]);
});

test("sample responses hand their commands to the registered handler", async () => {
  setup([]);
  const cmd = command("pause", 12);
  installFakeFetch(() => ({ status: 200, body: { processed: 1, commands: [cmd] } }));
  const received = [];
  setCommandHandler(list => received.push(...list));

  await sendSample({
    pairing_id: "p-1", source: "chrome", pc_name: "Desk", timestamp: new Date().toISOString(),
    downloads: [{ id: "12", filename: "a.iso", bytes_downloaded: 1, total_bytes: 2, state: "downloading" }]
  });
  await sleep(5);
  assert.deepEqual(received, [cmd]);
  setCommandHandler(handleCommands);
});

test("fetchCommands polls with the extension secret and dispatches the result", async () => {
  setup([]);
  const cmd = command("resume", 13);
  const calls = installFakeFetch(() => ({ status: 200, body: { commands: [cmd] } }));
  const received = [];
  setCommandHandler(list => received.push(...list));

  assert.equal(await fetchCommands(), 1);
  await sleep(5);
  assert.equal(calls[0].url, "https://api.example/v1/pairings/p-1/commands");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.headers.Authorization, "Bearer secret-A");
  assert.deepEqual(received, [cmd]);
  setCommandHandler(handleCommands);
});

test("fetchCommands does nothing while unpaired", async () => {
  setup([], { isPaired: false, pairingSecret: null });
  const calls = installFakeFetch(() => ({ status: 200, body: { commands: [] } }));
  assert.equal(await fetchCommands(), 0);
  assert.equal(calls.length, 0);
});

test("fetchCommands treats a 401 as revocation unless the secret was rotated", async () => {
  const { chromeState } = setup([]);
  installFakeFetch(() => {
    chromeState.store.pairingSecret = "secret-B";
    return { status: 401 };
  });
  await fetchCommands();
  assert.equal(chromeState.store.isPaired, true);

  installFakeFetch(() => ({ status: 401 }));
  await fetchCommands();
  assert.equal(chromeState.store.isPaired, false);
  assert.equal(chromeState.store.encryptionKey, null);
});

test("the command watch runs only while something is controllable and paired", async () => {
  const dl = running(14, { paused: true });
  const { chromeState } = setup([dl]);

  await updateCommandWatch();
  assert.ok(chromeState.alarms.has("hmd_command_watch"));

  dl.state = "complete";
  dl.paused = false;
  await updateCommandWatch();
  assert.ok(!chromeState.alarms.has("hmd_command_watch"));

  // Recently failed downloads can still be restarted from the phone
  dl.state = "interrupted";
  dl.endTime = new Date().toISOString();
  await updateCommandWatch();
  assert.ok(chromeState.alarms.has("hmd_command_watch"));

  chromeState.store.isPaired = false;
  await updateCommandWatch();
  assert.ok(!chromeState.alarms.has("hmd_command_watch"));
});

test("failed downloads report can_resume so the phone can offer resume", async () => {
  const { calls } = setup([running(15, { paused: true })]);
  // A finished item enters the sample through the onChanged path
  const { rememberFinished } = await import("./background/poller.js");
  globalThis.chrome.downloads.search = (orig => async query => {
    if (query.id === 16) return [running(16, { state: "interrupted", canResume: true })];
    return orig(query);
  })(globalThis.chrome.downloads.search);

  await rememberFinished(16);
  await pollAndSample();
  const failed = samples(calls).flatMap(s => s.downloads).find(d => d.id === "16");
  assert.equal(failed.state, "failed");
  assert.equal(failed.can_resume, true);
});
