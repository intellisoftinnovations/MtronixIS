/* Mtronix IS Offline Engine — IndexedDB catalog snapshot, outbox queue, auto-sync & PWA registration */
(function () {
  'use strict';

  const DB_NAME = 'mtronix_offline_v1';
  const DB_VERSION = 1;
  const SNAPSHOT_TTL_MS = 3 * 60 * 1000; // refresh snapshot every 3 minutes when online

  let dbPromise = null;
  let syncing = false;
  let deferredInstallPrompt = null;

  function openDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains('inventories')) db.createObjectStore('inventories', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('products')) db.createObjectStore('products', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('cartons')) db.createObjectStore('cartons', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('outbox')) db.createObjectStore('outbox', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta', { keyPath: 'key' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  function txDone(tx) {
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  async function getAll(storeName) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const req = db.transaction(storeName, 'readonly').objectStore(storeName).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function getMeta(key) {
    const db = await openDB();
    return new Promise((resolve) => {
      const req = db.transaction('meta', 'readonly').objectStore('meta').get(key);
      req.onsuccess = () => resolve(req.result ? req.result.value : null);
      req.onerror = () => resolve(null);
    });
  }

  async function setMeta(key, value) {
    const db = await openDB();
    const tx = db.transaction('meta', 'readwrite');
    tx.objectStore('meta').put({ key, value });
    return txDone(tx);
  }

  function generateUUID() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function getCSRFToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  async function saveSnapshot(data) {
    const db = await openDB();
    const tx = db.transaction(['inventories', 'products', 'cartons', 'meta'], 'readwrite');
    for (const name of ['inventories', 'products', 'cartons']) {
      const store = tx.objectStore(name);
      store.clear();
      (data[name] || []).forEach((item) => store.put(item));
    }
    tx.objectStore('meta').put({ key: 'last_snapshot_at', value: Date.now() });
    tx.objectStore('meta').put({ key: 'user_id', value: data.user_id });
    await txDone(tx);

    // Pre-warm product images into Service Worker cache for offline viewing
    if ('caches' in window && Array.isArray(data.products)) {
      const urls = data.products.map((p) => p.image_url).filter(Boolean).slice(0, 80);
      if (urls.length) {
        caches.open('mtx-media-mtx-v1').then((cache) => {
          urls.forEach((u) => {
            cache.match(u).then((hit) => {
              if (!hit) cache.add(u).catch(() => {});
            });
          });
        }).catch(() => {});
      }
    }
  }

  async function refreshSnapshot(force = false) {
    if (!navigator.onLine) return false;
    try {
      if (!force) {
        const last = await getMeta('last_snapshot_at');
        if (last && Date.now() - last < SNAPSHOT_TTL_MS) return true;
      }
      const res = await fetch('/api/offline/snapshot/', { credentials: 'same-origin' });
      if (!res.ok) return false;
      const contentType = res.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) return false;
      const data = await res.json();
      await saveSnapshot(data);
      return true;
    } catch (_) {
      return false;
    }
  }

  async function enqueue(item) {
    const db = await openDB();
    const record = Object.assign(
      {
        id: generateUUID(),
        idempotency_key: generateUUID(),
        created_at: new Date().toISOString(),
        error: null,
      },
      item
    );
    const tx = db.transaction('outbox', 'readwrite');
    tx.objectStore('outbox').put(record);
    await txDone(tx);

    // Apply optimistic carton count update locally so offline scans reflect pending changes
    if (record.kind === 'stock_movement' && record.carton_id) {
      const tx2 = db.transaction('cartons', 'readwrite');
      const store = tx2.objectStore('cartons');
      const existing = await new Promise((resolve) => {
        const r = store.get(Number(record.carton_id));
        r.onsuccess = () => resolve(r.result || null);
        r.onerror = () => resolve(null);
      });
      if (existing) {
        const delta = record.type === 'OUT' ? -Number(record.cartons) : Number(record.cartons);
        existing.carton_count = Math.max(0, Number(existing.carton_count) + delta);
        store.put(existing);
      }
      await txDone(tx2);
    }

    await updateStatusUI();
    return record;
  }

  async function removeOutboxItem(id) {
    const db = await openDB();
    const tx = db.transaction('outbox', 'readwrite');
    tx.objectStore('outbox').delete(id);
    await txDone(tx);
  }

  async function markOutboxError(id, errMsg) {
    const db = await openDB();
    const tx = db.transaction('outbox', 'readwrite');
    const store = tx.objectStore('outbox');
    const item = await new Promise((resolve) => {
      const r = store.get(id);
      r.onsuccess = () => resolve(r.result || null);
      r.onerror = () => resolve(null);
    });
    if (item) {
      item.error = errMsg;
      store.put(item);
    }
    await txDone(tx);
  }

  async function syncOutbox() {
    if (syncing || !navigator.onLine) return { synced: 0, errors: 0 };
    const items = await getAll('outbox');
    if (!items.length) {
      await updateStatusUI();
      return { synced: 0, errors: 0 };
    }

    syncing = true;
    await updateStatusUI('syncing');
    let synced = 0;
    let errors = 0;
    const csrf = getCSRFToken();

    try {
      // Sync items with image blobs via multipart/form-data one-by-one, and JSON items in a batch
      const jsonBatch = [];
      const blobItems = [];
      for (const item of items) {
        if (item.image_blob) blobItems.push(item);
        else jsonBatch.push(item);
      }

      if (jsonBatch.length) {
        const res = await fetch('/api/offline/sync/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrf,
          },
          body: JSON.stringify({ items: jsonBatch }),
        });
        if (res.ok) {
          const data = await res.json();
          for (const r of data.results || []) {
            if (r.status === 'ok') {
              await removeOutboxItem(r.id);
              synced++;
            } else {
              await markOutboxError(r.id, r.error || 'Sync failed');
              errors++;
            }
          }
        }
      }

      for (const item of blobItems) {
        const fd = new FormData();
        const payload = Object.assign({}, item);
        delete payload.image_blob;
        delete payload.image_name;
        fd.append('payload', JSON.stringify(payload));
        fd.append('image', item.image_blob, item.image_name || 'offline-photo.webp');

        const res = await fetch('/api/offline/sync/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRFToken': csrf },
          body: fd,
        });
        if (res.ok) {
          const data = await res.json();
          const r = (data.results || [])[0];
          if (r && r.status === 'ok') {
            await removeOutboxItem(item.id);
            synced++;
          } else {
            await markOutboxError(item.id, (r && r.error) || 'Sync failed');
            errors++;
          }
        }
      }

      if (synced > 0) {
        await refreshSnapshot(true);
      }
    } catch (_) {
      // Network dropped mid-sync; items remain safely queued
    } finally {
      syncing = false;
      await updateStatusUI();
    }

    return { synced, errors };
  }

  async function lookupCode(rawCode) {
    let code = String(rawCode || '').trim();
    if (!code) return null;
    const m = code.match(/\/q\/([A-Za-z0-9_\-]{10,64})\/?/);
    if (m) code = m[1];

    const [products, cartons, inventories] = await Promise.all([
      getAll('products'),
      getAll('cartons'),
      getAll('inventories'),
    ]);
    const prodById = new Map(products.map((p) => [p.id, p]));
    const invById = new Map(inventories.map((i) => [i.id, i]));
    const upper = code.toUpperCase();

    const enrichCarton = (c) => ({
      ...c,
      product: prodById.get(c.product_id) || null,
      inventory: invById.get(c.inventory_id) || null,
    });

    const byToken = cartons.find((c) => c.qr_token === code);
    if (byToken) return { mode: 'carton', carton: enrichCarton(byToken) };

    const prodByToken = products.find((p) => p.qr_token === code);
    if (prodByToken) {
      const matched = cartons.filter((c) => c.product_id === prodByToken.id).map(enrichCarton);
      return { mode: 'product', product: prodByToken, cartons: matched };
    }

    const byCode = cartons.filter((c) => (c.carton_code || '').toUpperCase() === upper).map(enrichCarton);
    if (byCode.length === 1) return { mode: 'carton', carton: byCode[0] };
    if (byCode.length > 1) return { mode: 'choose', code, cartons: byCode };

    const bySku = products.find((p) => (p.sku || '').toUpperCase() === upper);
    if (bySku) {
      const matched = cartons.filter((c) => c.product_id === bySku.id).map(enrichCarton);
      return { mode: 'product', product: bySku, cartons: matched };
    }

    return null;
  }

  async function clearAllOfflineData() {
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_USER_CACHES' });
      }
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(
          keys.filter((k) => k.includes('mtx-pages') || k.includes('mtx-media')).map((k) => caches.delete(k))
        );
      }
      if (dbPromise) {
        const db = await dbPromise;
        db.close();
        dbPromise = null;
      }
      indexedDB.deleteDatabase(DB_NAME);
    } catch (_) {}
  }

  async function updateStatusUI(stateOverride) {
    const bar = document.getElementById('offlineStatusBar');
    if (!bar) return;
    let items = [];
    try {
      items = await getAll('outbox');
    } catch (_) {}
    const count = items.length;
    const online = navigator.onLine;

    if (online && count === 0 && stateOverride !== 'syncing') {
      bar.hidden = true;
      return;
    }

    bar.hidden = false;
    bar.classList.toggle('is-offline', !online);
    const textEl = bar.querySelector('.offline-bar-text');
    const syncBtn = bar.querySelector('.offline-sync-btn');

    if (stateOverride === 'syncing') {
      textEl.textContent = `Syncing ${count} queued item${count === 1 ? '' : 's'}…`;
      if (syncBtn) syncBtn.hidden = true;
    } else if (!online) {
      textEl.textContent = count
        ? `Offline mode · ${count} change${count === 1 ? '' : 's'} queued for sync`
        : 'Offline mode · Using cached data';
      if (syncBtn) syncBtn.hidden = true;
    } else {
      const errCount = items.filter((i) => i.error).length;
      textEl.textContent = errCount
        ? `${count} pending (${errCount} need attention)`
        : `${count} offline change${count === 1 ? '' : 's'} ready to sync`;
      if (syncBtn) syncBtn.hidden = false;
    }
  }

  // Register Service Worker
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
    });
  }

  // Capture PWA Install prompt ("Add to Home Screen")
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    document.querySelectorAll('.pwa-install-btn').forEach((btn) => {
      btn.hidden = false;
    });
  });

  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    document.querySelectorAll('.pwa-install-btn').forEach((btn) => {
      btn.hidden = true;
    });
  });

  document.addEventListener('click', async (e) => {
    const installBtn = e.target.closest('.pwa-install-btn');
    if (installBtn && deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice;
      deferredInstallPrompt = null;
      document.querySelectorAll('.pwa-install-btn').forEach((btn) => {
        btn.hidden = true;
      });
    }
    if (e.target.closest('.offline-sync-btn')) {
      syncOutbox();
    }
  });

  // Wipe offline user caches on explicit logout
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (form && form.action && form.action.includes('/logout/')) {
      clearAllOfflineData();
    }
  });

  window.addEventListener('online', () => {
    updateStatusUI();
    syncOutbox().then(() => refreshSnapshot(false));
  });
  window.addEventListener('offline', () => {
    updateStatusUI();
  });

  document.addEventListener('DOMContentLoaded', () => {
    updateStatusUI();
    if (navigator.onLine) {
      syncOutbox().then(() => refreshSnapshot(false));
    }
  });

  window.MtronixOffline = {
    refreshSnapshot,
    enqueue,
    syncOutbox,
    lookupCode,
    getOutbox: () => getAll('outbox'),
    clearAllOfflineData,
    updateStatusUI,
    generateUUID,
  };
})();
