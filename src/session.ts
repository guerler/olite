/** Session persistence: pi keeps session.jsonl per analysis directory; the browser gets IndexedDB. */

const DB_NAME = "olite";
const STORE_NAME = "sessions";
const VERSION = 1;

/** The mechanism, kept behind an interface so the policy below is testable without IndexedDB. */
export interface Store {
    get(key: string): Promise<unknown>;
    put(key: string, value: unknown): Promise<void>;
    remove(key: string): Promise<void>;
}

export function indexedDbStore(factory: IDBFactory | undefined = globalThis.indexedDB): Store | null {
    if (!factory) {
        return null;
    }
    const open = () =>
        new Promise<IDBDatabase>((resolve, reject) => {
            const req = factory.open(DB_NAME, VERSION);
            req.onupgradeneeded = () => req.result.createObjectStore(STORE_NAME);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    const run = async (mode: IDBTransactionMode, act: (s: IDBObjectStore) => IDBRequest) => {
        const db = await open();
        try {
            return await new Promise<any>((resolve, reject) => {
                const req = act(db.transaction(STORE_NAME, mode).objectStore(STORE_NAME));
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
            });
        } finally {
            db.close();
        }
    };
    return {
        get: (key) => run("readonly", (s) => s.get(key)),
        put: async (key, value) => {
            await run("readwrite", (s) => s.put(value, key));
        },
        remove: async (key) => {
            await run("readwrite", (s) => s.delete(key));
        },
    };
}

/** One stored conversation per Galaxy history, as pi keys a session by its analysis directory. */
export class SessionMemory {
    constructor(
        private store: Store | null,
        private historyId?: string,
    ) {}

    /** No history means no session to key on: the eval harness and the dev page keep none. */
    get enabled(): boolean {
        return Boolean(this.store && this.historyId);
    }

    private get key(): string {
        return `session:${this.historyId}`;
    }

    async load(): Promise<any[] | null> {
        if (!this.enabled) {
            return null;
        }
        try {
            const stored = await this.store!.get(this.key);
            return Array.isArray(stored) && stored.every(isMessage) && stored.length ? stored : null;
        } catch {
            return null;
        }
    }

    /** Persisting must never break a turn, so a failed write is dropped rather than raised. */
    async save(messages: any[]): Promise<void> {
        if (!this.enabled || !hasConversation(messages)) {
            return;
        }
        try {
            await this.store!.put(this.key, messages);
        } catch (e) {
            console.warn("[olite] could not persist the session", e);
        }
    }

    async clear(): Promise<void> {
        if (!this.enabled) {
            return;
        }
        try {
            await this.store!.remove(this.key);
        } catch (e) {
            console.warn("[olite] could not clear the session", e);
        }
    }
}

function isMessage(m: unknown): boolean {
    return Boolean(m && typeof m === "object" && typeof (m as any).role === "string");
}

/** A seeded system prompt on its own is not a conversation worth resuming. */
function hasConversation(messages: any[]): boolean {
    return Array.isArray(messages) && messages.some((m) => isMessage(m) && m.role !== "system");
}
