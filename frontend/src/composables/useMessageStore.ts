import { ref } from 'vue'
import type { ChatMessage } from '@/types/chat'

const DB_NAME = 'animetta-messages'
const DB_VERSION = 1
const STORE_NAME = 'messages'

let dbPromise: Promise<IDBDatabase> | null = null

function openMessageDB(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION)

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' })
          store.createIndex('role', 'role', { unique: false })
          store.createIndex('timestamp', 'timestamp', { unique: false })
        }
      }

      request.onsuccess = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        db.onversionchange = () => {
          db.close()
          dbPromise = null
        }
        resolve(db)
      }

      request.onerror = (event) => {
        dbPromise = null
        reject((event.target as IDBOpenDBRequest).error)
      }
    })
  }
  return dbPromise
}

export function useMessageStore() {
  const isReady = ref(false)

  openMessageDB()
    .then(() => {
      isReady.value = true
    })
    .catch(() => {})

  async function saveMessages(messages: ChatMessage[]): Promise<void> {
    const db = await openMessageDB()
    return new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      store.clear()
      for (const msg of messages) {
        store.add(msg)
      }
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  }

  async function loadMessages(): Promise<ChatMessage[]> {
    const db = await openMessageDB()
    return new Promise<ChatMessage[]>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const store = tx.objectStore(STORE_NAME)
      const index = store.index('timestamp')
      const request = index.getAll()
      request.onsuccess = () => resolve(request.result as ChatMessage[])
      request.onerror = () => reject(request.error)
    })
  }

  async function pruneMessages(maxCount = 500): Promise<void> {
    const db = await openMessageDB()
    const tx = db.transaction(STORE_NAME, 'readonly')
    const store = tx.objectStore(STORE_NAME)
    const index = store.index('timestamp')
    const all = await new Promise<ChatMessage[]>((resolve, reject) => {
      const req = index.getAll()
      req.onsuccess = () => resolve(req.result as ChatMessage[])
      req.onerror = () => reject(req.error)
    })
    if (all.length <= maxCount) return

    const toDelete = all.slice(0, all.length - maxCount)
    const writeTx = db.transaction(STORE_NAME, 'readwrite')
    const writeStore = writeTx.objectStore(STORE_NAME)
    return new Promise<void>((resolve, reject) => {
      for (const msg of toDelete) {
        writeStore.delete(msg.id)
      }
      writeTx.oncomplete = () => resolve()
      writeTx.onerror = () => reject(writeTx.error)
    })
  }

  return { saveMessages, loadMessages, pruneMessages, isReady }
}
