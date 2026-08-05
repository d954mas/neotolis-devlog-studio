export type VoiceDraft = {
  blob: Blob;
  elapsedMs: number;
  recordedAt: string;
  productionId: string;
  scriptRef: { sha256: string; size: number };
};

const DATABASE = "dlstudio-voice";
const STORE = "drafts";
function draftKey(productionId: string, scriptRef: { sha256: string; size: number }): string {
  return `${productionId}:${scriptRef.sha256}:${scriptRef.size}`;
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Не удалось открыть хранилище черновиков."));
  });
}

async function transaction<T>(
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const database = await openDatabase();
  return await new Promise<T>((resolve, reject) => {
    const idbTransaction = database.transaction(STORE, mode);
    const request = action(idbTransaction.objectStore(STORE));
    const fail = () => {
      database.close();
      reject(
        request.error ?? idbTransaction.error ??
          new Error("Ошибка хранилища черновиков."),
      );
    };
    request.onerror = fail;
    idbTransaction.onerror = fail;
    idbTransaction.oncomplete = () => {
      const result = request.result;
      database.close();
      resolve(result);
    };
  });
}

export function saveVoiceDraft(draft: VoiceDraft): Promise<IDBValidKey> {
  return transaction("readwrite", (store) => store.put(draft, draftKey(draft.productionId, draft.scriptRef)));
}

export async function loadVoiceDraft(
  productionId: string,
  scriptRef: { sha256: string; size: number },
): Promise<VoiceDraft | null> {
  return (await transaction("readonly", (store) => store.get(draftKey(productionId, scriptRef)))) ?? null;
}

export async function deleteVoiceDraft(
  productionId: string,
  scriptRef: { sha256: string; size: number },
): Promise<void> {
  await transaction("readwrite", (store) => store.delete(draftKey(productionId, scriptRef)));
}
