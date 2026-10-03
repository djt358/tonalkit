// Keeps the session and its kept takes in IndexedDB, so a closed tab resumes where it left off.
// Nothing here leaves the phone. Falls back to memory (persistent: false) where IndexedDB isn't
// available, and the app says progress won't survive a reload.

const DB_NAME = "tonekit-kit";
const DB_VERSION = 1;
const SESSIONS = "session"; // key "current" -> the session record
const CLIPS = "clips"; // key card id -> Uint8Array (the kept take's WAV)
const CURRENT = "current";

const done = (request) =>
  new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

const committed = (tx) =>
  new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error("transaction aborted"));
  });

function openDb(idb) {
  const request = idb.open(DB_NAME, DB_VERSION);
  request.onupgradeneeded = () => {
    const db = request.result;
    if (!db.objectStoreNames.contains(SESSIONS)) db.createObjectStore(SESSIONS);
    if (!db.objectStoreNames.contains(CLIPS)) db.createObjectStore(CLIPS);
  };
  return done(request);
}

function idbStore(db) {
  return {
    persistent: true,
    async loadSession() {
      return (await done(db.transaction(SESSIONS).objectStore(SESSIONS).get(CURRENT))) ?? null;
    },
    /** Saves the session, and a kept take with it in the same transaction. */
    async save(session, clip = null) {
      const tx = db.transaction([SESSIONS, CLIPS], "readwrite");
      if (clip) tx.objectStore(CLIPS).put(clip.wav, clip.id);
      tx.objectStore(SESSIONS).put(session, CURRENT);
      await committed(tx);
    },
    async getClip(id) {
      return (await done(db.transaction(CLIPS).objectStore(CLIPS).get(id))) ?? null;
    },
    async clear() {
      const tx = db.transaction([SESSIONS, CLIPS], "readwrite");
      tx.objectStore(SESSIONS).clear();
      tx.objectStore(CLIPS).clear();
      await committed(tx);
    },
  };
}

function memoryStore() {
  let session = null;
  const clips = new Map();
  return {
    persistent: false,
    loadSession: async () => (session ? structuredClone(session) : null),
    save: async (s, clip = null) => {
      if (clip) clips.set(clip.id, clip.wav);
      session = structuredClone(s);
    },
    getClip: async (id) => clips.get(id) ?? null,
    clear: async () => {
      session = null;
      clips.clear();
    },
  };
}

export async function openStore(idb = globalThis.indexedDB) {
  try {
    if (!idb) throw new Error("no IndexedDB");
    const store = idbStore(await openDb(idb));
    await store.loadSession(); // fails early where storage is blocked
    globalThis.navigator?.storage?.persist?.().catch(() => {});
    return store;
  } catch {
    return memoryStore();
  }
}
