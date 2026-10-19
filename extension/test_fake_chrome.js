/**
 * Minimal in-memory stand-ins for the chrome.* and fetch APIs used by the background modules,
 * so tests exercise the real extension code under Node.
 */

export function installFakeChrome({ storage = {}, downloads = [] } = {}) {
  const store = { ...storage };
  const state = { store, downloads, messages: [] };

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
      async search(query) {
        return state.downloads.filter(d => !query.state || d.state === query.state);
      }
    },
    alarms: { create() {}, clear() {} }
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
