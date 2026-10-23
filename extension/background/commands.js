/**
 * Executes phone commands (pause / resume / restart) against chrome.downloads.
 *
 * Commands come from the server, so everything is validated: the action must be one of three,
 * the download must exist in this browser, and a restart only re-fetches the download's own
 * http(s)/ftp URL. Successes need no report (the next sample shows the new state); failures
 * are reported with a fixed error code, which the server forwards to the phone.
 */

import { reportCommandResult } from "./api.js";
import { markRestarted, rememberFinished, requestImmediateSample, unmarkRestarted } from "./poller.js";

const ACTIONS = new Set(["pause", "resume", "restart"]);
const COMMAND_ID_RE = /^[0-9a-f]{32}$/;
const CHROME_DOWNLOAD_ID_RE = /^\d{1,15}$/;
const RESTARTABLE_URL_RE = /^(https?|ftp):/i;
const MAX_REMEMBERED_COMMANDS = 100;

// Commands already executed, in case the same one is delivered twice
const handledCommandIds = new Set();

export class CommandError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

export function isValidCommand(command) {
  return Boolean(command)
    && typeof command.command_id === "string" && COMMAND_ID_RE.test(command.command_id)
    && ACTIONS.has(command.action)
    && typeof command.download_id === "string" && CHROME_DOWNLOAD_ID_RE.test(command.download_id);
}

async function pause(item) {
  if (item.state !== "in_progress") throw new CommandError("invalid_state");
  if (!item.paused) await chrome.downloads.pause(item.id);
}

async function resume(item) {
  if (item.state === "in_progress") {
    if (item.paused) await chrome.downloads.resume(item.id);
    return;
  }
  if (item.state === "interrupted") {
    if (!item.canResume) throw new CommandError("not_resumable");
    await chrome.downloads.resume(item.id);
    return;
  }
  throw new CommandError("invalid_state"); // already complete
}

/**
 * Starts the download over from byte 0: cancels it if still running, downloads the original
 * URL again, and removes the superseded entry from Chrome's list. The new download gets a new
 * id; the old one is reported once as "erased" so the phone drops its notification.
 */
async function restart(item) {
  if (item.state === "complete") throw new CommandError("invalid_state");
  // The original URL re-resolves redirects (finalUrl may be an expired signed link)
  const url = item.url || item.finalUrl;
  if (!url || !RESTARTABLE_URL_RE.test(url)) throw new CommandError("unsupported_url");

  markRestarted(item);
  let cancelled = false;
  try {
    if (item.state === "in_progress") {
      await chrome.downloads.cancel(item.id);
      cancelled = true;
    }
    await chrome.downloads.download({ url });
  } catch (err) {
    unmarkRestarted(item.id);
    // A cancelled download that could not be re-started must still show up as failed
    if (cancelled) await rememberFinished(item.id);
    throw err;
  }
  try {
    await chrome.downloads.erase({ id: item.id });
  } catch (err) {
    console.warn(`[How's My Download] Could not remove restarted download ${item.id}:`, err);
  }
}

/**
 * Runs one validated command. Throws CommandError (or a Chrome error) on failure.
 */
export async function executeCommand(command) {
  const [item] = await chrome.downloads.search({ id: Number(command.download_id) });
  if (!item) throw new CommandError("not_found");

  switch (command.action) {
    case "pause":
      return pause(item);
    case "resume":
      return resume(item);
    case "restart":
      return restart(item);
    default:
      throw new CommandError("invalid_state");
  }
}

/**
 * Entry point registered with api.js: executes each new command in order, reports failures,
 * then samples immediately so the phone sees the outcome.
 */
export async function handleCommands(commands) {
  let handled = 0;
  for (const command of commands) {
    if (!isValidCommand(command)) {
      console.warn("[How's My Download] Ignoring malformed command from server.");
      continue;
    }
    if (handledCommandIds.has(command.command_id)) continue;
    handledCommandIds.add(command.command_id);
    while (handledCommandIds.size > MAX_REMEMBERED_COMMANDS) {
      handledCommandIds.delete(handledCommandIds.values().next().value);
    }
    handled++;

    try {
      await executeCommand(command);
      console.log(`[How's My Download] Phone command: ${command.action} download ${command.download_id}`);
    } catch (err) {
      const code = err instanceof CommandError ? err.code : "browser_error";
      console.warn(`[How's My Download] Phone command ${command.action} on ${command.download_id} failed: ${err.message || code}`);
      await reportCommandResult(command, false, code);
    }
  }
  if (handled > 0) requestImmediateSample();
}
