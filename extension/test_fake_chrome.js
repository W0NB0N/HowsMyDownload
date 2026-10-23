/**
 * Minimal in-memory stand-ins for the chrome.* and fetch APIs used by the background modules,
 * so tests exercise the real extension code under Node.
 */

export function installFakeChrome({ storage = {}, downloads = [] } = {}) {
  const store = { ...storage };
  const alarms = new Map();
  // Records every chrome.downloads mutation as [method, arg]
  const downloadCalls = [];
  const state = { store, downloads, messages: [], alarms, downloadCalls, nextDownloadId: 1000 };

  const find = id => state.downloads.find(d => d.id === id);
  const requireItem = id => {
    const item = find(id);
    if (!item) throw new Error(`Invalid download id ${id}`);
    return item;
  };

  globalThis.chrome = {
    storage: {
      local: {
        async get(keys) {
          if (keys == null) return { ...store };
          if (typeof keys === "string") return { [keys]: store[keys] };
          if (Array.isArray(keys)) return Object.fromEntries(keys.map(k => [k, store[k]]));
          return Object.fromEntries(
            Object.entries(keys).map(([k, dflt]) => [k, k in store ? store[k] : dflt])
          );
        },
        async set(values) {
          Object.assign(store, values);
        }
      }
    },
    runtime: {
      sendMessage(message) {
        state.messages.push(message);
        return Promise.resolve();
      }
    },
    downloads: {
      async search(query = {}) {
        return state.downloads.filter(d =>
          (query.id === undefined || d.id === query.id)
          && (!query.state || d.state === query.state)
          && (query.paused === undefined || Boolean(d.paused) === query.paused)
          && (!query.endedAfter || !d.endTime || d.endTime > query.endedAfter)
        );
      },
      async pause(id) {
        downloadCalls.push(["pause", id]);
        requireItem(id).paused = true;
      },
      async resume(id) {
        downloadCalls.push(["resume", id]);
        const item = requireItem(id);
        item.paused = false;
        item.state = "in_progress";
      },
      async cancel(id) {
        downloadCalls.push(["cancel", id]);
        const item = requireItem(id);
        item.state = "interrupted";
        item.error = "USER_CANCELED";
      },
      async download(options) {
        downloadCalls.push(["download", options]);
        if (state.failNextDownload) {
          state.failNextDownload = false;
          throw new Error("Download failed to start");
        }
        const id = state.nextDownloadId++;
        state.downloads.push({
          id, url: options.url, filename: "", state: "in_progress", paused: false,
          bytesReceived: 0, totalBytes: -1
        });
        return id;
      },
      async erase(query) {
        downloadCalls.push(["erase", query]);
        state.downloads = state.downloads.filter(d => d.id !== query.id);
        return [query.id];
      }
    },
    alarms: {
      create(name, info) { alarms.set(name, info); },
      clear(name) { alarms.delete(name); return Promise.resolve(true); },
      async get(name) { return alarms.has(name) ? { name, ...alarms.get(name) } : undefined; }
    }
  };
  return state;
}

/**
 * Replaces global fetch. `handler(url, options, callIndex)` returns {status, body}.
 * Returns the array of recorded calls.
 */
export function installFakeFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    const { status = 200, body = {} } = (await handler(url, options, calls.length - 1)) || {};
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: String(status),
      json: async () => body
    };
  };
  return calls;
}

export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
