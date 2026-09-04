"""Resumable, client-compressed photo uploader for Drop Vinted."""

from __future__ import annotations

try:
    import streamlit.components.v2 as components_v2
except Exception:  # pragma: no cover - depends on the Streamlit runtime
    components_v2 = None


_component = None


def component_available() -> bool:
    return components_v2 is not None


def _get_component():
    global _component
    if components_v2 is None:
        return None
    if _component is not None:
        return _component

    html = r"""
    <section class="upload-shell">
      <div class="upload-heading">
        <div>
          <strong>Importer les photos depuis cet appareil</strong>
          <p>Les images sont allégées sur cet appareil avant leur envoi.</p>
        </div>
        <span class="state-badge">Prêt</span>
      </div>
      <input class="file-input" type="file" multiple
             accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" />
      <div class="progress-copy">
        <span class="photo-progress">Photos : 0 / 0</span>
        <span class="compression-progress">Compression : 0 / 0</span>
        <span class="upload-progress">Envoyées : 0 / 0</span>
      </div>
      <div class="progress-track"><span></span></div>
      <div class="order-preview" hidden>
        <div class="preview-item first-preview"></div>
        <div class="preview-copy"><strong>Ordre conservé</strong><span class="order-copy"></span></div>
        <div class="preview-item last-preview"></div>
      </div>
      <div class="actions">
        <button class="select-button primary" type="button">Ajouter des photos</button>
        <button class="retry-button" type="button" hidden>Réessayer les erreurs</button>
        <button class="cancel-button" type="button" hidden>Annuler l’import</button>
      </div>
      <button class="analyze-button primary wide" type="button" disabled>Analyser les photos</button>
      <details class="details" hidden><summary>Détails et erreurs</summary><div class="error-list"></div></details>
    </section>
    """
    css = r"""
    :host { color: #111827; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    .upload-shell { border: 1px solid #e5e7eb; border-radius: 9px; background: #fff; padding: 16px; }
    .upload-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
    .upload-heading strong { display: block; font-size: 15px; line-height: 1.35; }
    .upload-heading p { margin: 4px 0 0; color: #6b7280; font-size: 13px; }
    .state-badge { flex: 0 0 auto; border: 1px solid #e5e7eb; border-radius: 999px; padding: 4px 9px; color: #4b5563; font-size: 12px; font-weight: 650; }
    .state-badge.ready { border-color: #bbf7d0; color: #15803d; background: #f0fdf4; }
    .state-badge.error { border-color: #fecaca; color: #b91c1c; background: #fef2f2; }
    .file-input { display: none; }
    .progress-copy { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 16px; color: #4b5563; font-size: 12px; }
    .progress-track { height: 6px; margin-top: 8px; overflow: hidden; border-radius: 999px; background: #eef0f3; }
    .progress-track span { display: block; width: 0; height: 100%; border-radius: inherit; background: #6d28d9; transition: width 160ms ease; }
    .order-preview { display: grid; grid-template-columns: 54px minmax(0, 1fr) 54px; align-items: center; gap: 10px; margin-top: 14px; padding: 10px; border: 1px solid #e5e7eb; border-radius: 8px; background: #f9fafb; }
    .preview-item { width: 54px; height: 54px; overflow: hidden; border: 1px solid #e5e7eb; border-radius: 6px; background: #fff; }
    .preview-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .preview-copy { min-width: 0; }
    .preview-copy strong, .preview-copy span { display: block; }
    .preview-copy strong { font-size: 13px; }
    .preview-copy span { margin-top: 2px; color: #6b7280; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    button { min-height: 38px; border: 1px solid #d1d5db; border-radius: 7px; background: #fff; color: #111827; padding: 0 13px; font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; transition: background 120ms ease, border-color 120ms ease, transform 80ms ease; }
    button:hover:not(:disabled) { border-color: #9ca3af; background: #f9fafb; }
    button:active:not(:disabled) { transform: translateY(1px); }
    button.primary { border-color: #6d28d9; background: #6d28d9; color: #fff; }
    button.primary:hover:not(:disabled) { border-color: #5b21b6; background: #5b21b6; }
    button:disabled { cursor: not-allowed; opacity: .5; }
    button.wide { width: 100%; margin-top: 10px; }
    .details { margin-top: 12px; color: #4b5563; font-size: 12px; }
    .details summary { cursor: pointer; font-weight: 650; }
    .error-list { display: grid; gap: 5px; margin-top: 8px; }
    .error-row { padding: 7px 9px; border-left: 2px solid #dc2626; background: #fef2f2; color: #991b1b; }
    [hidden] { display: none !important; }
    @media (max-width: 520px) {
      .upload-shell { padding: 14px; }
      .upload-heading { display: block; }
      .state-badge { display: inline-block; margin-top: 10px; }
      .actions button { width: 100%; }
      .order-preview { grid-template-columns: 46px minmax(0, 1fr) 46px; }
      .preview-item { width: 46px; height: 46px; }
    }
    """
    js = r"""
    const DB_NAME = "pokestock-photo-upload-v1";
    const DB_VERSION = 1;
    const registry = window.__pokestockPhotoUploadControllers || (window.__pokestockPhotoUploadControllers = {});

    function openDb() {
      return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
          const db = request.result;
          const meta = db.createObjectStore("photo_meta", { keyPath: "client_id" });
          meta.createIndex("session_hash", "session_hash", { unique: true });
          db.createObjectStore("photo_blob", { keyPath: "client_id" });
          db.createObjectStore("app_meta", { keyPath: "key" });
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("IndexedDB indisponible"));
      });
    }

    function requestResult(request) {
      return new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    }

    function transactionDone(transaction) {
      return new Promise((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error || new Error("Transaction annulée"));
      });
    }

    async function getAppMeta(db, key, fallback = null) {
      const tx = db.transaction("app_meta", "readonly");
      const row = await requestResult(tx.objectStore("app_meta").get(key));
      return row ? row.value : fallback;
    }

    async function setAppMeta(db, key, value) {
      const tx = db.transaction("app_meta", "readwrite");
      tx.objectStore("app_meta").put({ key, value });
      await transactionDone(tx);
    }

    async function sessionMetas(db, sessionId) {
      const tx = db.transaction("photo_meta", "readonly");
      const rows = await requestResult(tx.objectStore("photo_meta").getAll());
      return rows.filter(row => row.upload_session_id === sessionId)
        .sort((a, b) => Number(a.original_index ?? 0) - Number(b.original_index ?? 0));
    }

    async function putPhoto(db, meta, blob) {
      const tx = db.transaction(["photo_meta", "photo_blob"], "readwrite");
      tx.objectStore("photo_meta").put(meta);
      tx.objectStore("photo_blob").put({ client_id: meta.client_id, blob });
      await transactionDone(tx);
    }

    async function putMeta(db, meta) {
      const tx = db.transaction("photo_meta", "readwrite");
      tx.objectStore("photo_meta").put(meta);
      await transactionDone(tx);
    }

    async function getBlob(db, clientId) {
      const tx = db.transaction("photo_blob", "readonly");
      const row = await requestResult(tx.objectStore("photo_blob").get(clientId));
      return row && row.blob;
    }

    async function deleteMeta(db, clientId) {
      const tx = db.transaction(["photo_meta", "photo_blob"], "readwrite");
      tx.objectStore("photo_meta").delete(clientId);
      tx.objectStore("photo_blob").delete(clientId);
      await transactionDone(tx);
    }

    async function clearSession(db, sessionId) {
      const rows = await sessionMetas(db, sessionId);
      const tx = db.transaction(["photo_meta", "photo_blob"], "readwrite");
      for (const row of rows) {
        tx.objectStore("photo_meta").delete(row.client_id);
        tx.objectStore("photo_blob").delete(row.client_id);
      }
      await transactionDone(tx);
    }

    function bytesToBase64(bytes) {
      let binary = "";
      const chunk = 0x8000;
      for (let offset = 0; offset < bytes.length; offset += chunk) {
        binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunk, bytes.length)));
      }
      return btoa(binary);
    }

    async function sha256(blob) {
      const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
      return Array.from(new Uint8Array(digest)).map(value => value.toString(16).padStart(2, "0")).join("");
    }

    async function decodeImage(file) {
      if (typeof createImageBitmap === "function") {
        try {
          return await createImageBitmap(file, { imageOrientation: "from-image" });
        } catch (error) {}
      }
      return await new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const image = new Image();
        image.onload = () => {
          URL.revokeObjectURL(url);
          resolve(image);
        };
        image.onerror = () => {
          URL.revokeObjectURL(url);
          reject(new Error("Format non décodable par ce navigateur"));
        };
        image.src = url;
      });
    }

    async function compressImage(file, maxDimension, quality) {
      const decoded = await decodeImage(file);
      const width = Number(decoded.width || decoded.naturalWidth || 0);
      const height = Number(decoded.height || decoded.naturalHeight || 0);
      if (!width || !height) throw new Error("Dimensions illisibles");
      const scale = Math.min(1, maxDimension / Math.max(width, height));
      const outputWidth = Math.max(1, Math.round(width * scale));
      const outputHeight = Math.max(1, Math.round(height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = outputWidth;
      canvas.height = outputHeight;
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) throw new Error("Compression indisponible");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, outputWidth, outputHeight);
      context.drawImage(decoded, 0, 0, outputWidth, outputHeight);
      if (decoded.close) decoded.close();
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(value => value ? resolve(value) : reject(new Error("Compression impossible")), "image/jpeg", quality);
      });
      canvas.width = 1;
      canvas.height = 1;
      return { blob, width: outputWidth, height: outputHeight };
    }

    function uuid(prefix) {
      const value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      return `${prefix}_${value}`;
    }

    export default function(component) {
      const { data, parentElement, setTriggerValue } = component;
      const config = data || {};
      const dropId = String(config.drop_id || "unknown");
      const controllerKey = `drop:${dropId}`;
      const controller = registry[controllerKey] || (registry[controllerKey] = {
        pendingFiles: [], failedFiles: new Map(), processing: false, inFlight: false,
        compressedThisRun: 0, selectedThisRun: 0, duplicateCount: 0,
        previewUrls: [], view: null, trigger: null, db: null, sessionId: ""
      });
      controller.view = parentElement;
      controller.trigger = setTriggerValue;
      controller.config = config;

      const query = selector => parentElement.querySelector(selector);
      const fileInput = query(".file-input");
      const selectButton = query(".select-button");
      const retryButton = query(".retry-button");
      const cancelButton = query(".cancel-button");
      const analyzeButton = query(".analyze-button");
      const disabled = Boolean(config.disabled);
      selectButton.disabled = disabled;
      selectButton.textContent = disabled ? "Import indisponible pour ce Drop lancé" : "Ajouter des photos";

      async function initialize() {
        try {
          controller.db = controller.db || await openDb();
          const sessionKey = `session:${dropId}`;
          controller.sessionId = controller.sessionId
            || String(config.upload_session_id || "")
            || String(await getAppMeta(controller.db, sessionKey, ""))
            || uuid("upload");
          await setAppMeta(controller.db, sessionKey, controller.sessionId);

          const cancelToken = String(config.cancel_token || "");
          const lastCancelToken = String(await getAppMeta(controller.db, `cancel:${controller.sessionId}`, ""));
          if (cancelToken && cancelToken !== lastCancelToken) {
            await clearSession(controller.db, controller.sessionId);
            await setAppMeta(controller.db, `cancel:${controller.sessionId}`, cancelToken);
            await setAppMeta(controller.db, `next-index:${controller.sessionId}`, 0);
            await setAppMeta(controller.db, `next-batch:${controller.sessionId}`, 0);
            controller.pendingFiles = [];
            controller.failedFiles.clear();
            controller.processing = false;
            controller.inFlight = false;
          }

          const received = new Set(config.received_hashes || []);
          const rows = await sessionMetas(controller.db, controller.sessionId);
          const ackRows = Array.isArray(config.ack && config.ack.acknowledgements)
            ? config.ack.acknowledgements : [];
          const ackByClient = new Map(ackRows.map(row => [String(row.client_id || ""), row]));
          for (const row of rows) {
            if (!row.hash) continue;
            const ack = ackByClient.get(row.client_id);
            const status = received.has(row.hash)
              ? "uploaded"
              : ack && ack.status === "error"
                ? "error"
                : (row.status === "compression_error" ? row.status : "queued");
            const error = ack && ack.status === "error" ? String(ack.message || "Envoi impossible") : (status === "error" ? row.error : "");
            if (row.status !== status || row.error !== error) await putMeta(controller.db, { ...row, status, error });
          }
          controller.inFlight = false;
          selectButton.disabled = disabled;
          await renderState();
          await sendNextBatch();
        } catch (error) {
          showFatal(error);
        }
      }

      async function renderPreview(rows) {
        for (const url of controller.previewUrls) URL.revokeObjectURL(url);
        controller.previewUrls = [];
        const preview = query(".order-preview");
        if (!rows.length) {
          preview.hidden = true;
          return;
        }
        preview.hidden = false;
        const first = rows[0];
        const last = rows[rows.length - 1];
        for (const [row, selector] of [[first, ".first-preview"], [last, ".last-preview"]]) {
          const target = query(selector);
          target.innerHTML = "";
          const blob = await getBlob(controller.db, row.client_id);
          if (blob) {
            const url = URL.createObjectURL(blob);
            controller.previewUrls.push(url);
            const image = document.createElement("img");
            image.src = url;
            image.alt = row.original_filename || "Photo";
            target.appendChild(image);
          }
        }
        query(".order-copy").textContent = `${rows.length} photo${rows.length > 1 ? "s" : ""} prête${rows.length > 1 ? "s" : ""} · de ${first.original_filename} à ${last.original_filename}`;
      }

      async function renderState() {
        if (!controller.db || !controller.sessionId) return;
        const rows = await sessionMetas(controller.db, controller.sessionId);
        const errors = rows.filter(row => row.status === "error" || row.status === "compression_error");
        const uploaded = rows.filter(row => row.status === "uploaded").length;
        const compressed = rows.filter(row => row.status !== "compression_error").length;
        const pending = controller.pendingFiles.length + (controller.processing ? 1 : 0);
        const total = rows.length + pending;
        query(".photo-progress").textContent = `Photos : ${uploaded} / ${total}${controller.duplicateCount ? ` · ${controller.duplicateCount} déjà importée${controller.duplicateCount > 1 ? "s" : ""}` : ""}`;
        query(".compression-progress").textContent = `Compression : ${compressed} / ${total}`;
        query(".upload-progress").textContent = `Envoyées : ${uploaded} / ${total}`;
        query(".progress-track span").style.width = `${total ? Math.round(uploaded / total * 100) : 0}%`;
        const badge = query(".state-badge");
        badge.className = "state-badge";
        if (errors.length) {
          badge.textContent = `${errors.length} erreur${errors.length > 1 ? "s" : ""}`;
          badge.classList.add("error");
        } else if (total > 0 && uploaded === total && !controller.processing && !controller.inFlight) {
          badge.textContent = "Photos prêtes";
          badge.classList.add("ready");
        } else if (controller.processing) {
          badge.textContent = "Compression";
        } else if (controller.inFlight || uploaded < total) {
          badge.textContent = "Envoi en cours";
        } else {
          badge.textContent = "Prêt";
        }
        retryButton.hidden = !errors.length;
        cancelButton.hidden = !total;
        analyzeButton.hidden = !config.show_analyze_action;
        analyzeButton.disabled = disabled || !total || uploaded !== total || errors.length > 0 || controller.processing || controller.inFlight;
        const details = query(".details");
        details.hidden = !errors.length;
        query(".error-list").innerHTML = errors.slice(0, 20).map(row =>
          `<div class="error-row"><strong>${escapeHtml(row.original_filename || "Photo")}</strong> · ${escapeHtml(row.error || "Envoi impossible")}</div>`
        ).join("");
        await renderPreview(rows.filter(row => row.status !== "compression_error"));
      }

      function escapeHtml(value) {
        return String(value || "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
      }

      function showFatal(error) {
        const badge = query(".state-badge");
        badge.textContent = "Import indisponible";
        badge.className = "state-badge error";
        const details = query(".details");
        details.hidden = false;
        query(".error-list").innerHTML = `<div class="error-row">${escapeHtml(error && error.message || error)}</div>`;
      }

      async function findDuplicate(hash) {
        const tx = controller.db.transaction("photo_meta", "readonly");
        return await requestResult(tx.objectStore("photo_meta").index("session_hash").get(`${controller.sessionId}:${hash}`));
      }

      async function recordCompressionError(job, error) {
        const clientId = uuid("error");
        controller.failedFiles.set(clientId, job);
        await putMeta(controller.db, {
          client_id: clientId,
          upload_session_id: controller.sessionId,
          session_hash: `${controller.sessionId}:error:${clientId}`,
          original_filename: job.file.name || "Photo",
          original_index: Number.MAX_SAFE_INTEGER - controller.failedFiles.size,
          batch_index: job.batchIndex,
          status: "compression_error",
          error: error && error.message || "Format non décodable"
        });
      }

      async function processQueue() {
        if (controller.processing || disabled) return;
        controller.processing = true;
        while (controller.pendingFiles.length) {
          const job = controller.pendingFiles.shift();
          try {
            const output = await compressImage(job.file, Number(config.max_dimension || 2048), Number(config.jpeg_quality || .89));
            const hash = await sha256(output.blob);
            if (await findDuplicate(hash)) {
              controller.duplicateCount += 1;
              continue;
            }
            const nextKey = `next-index:${controller.sessionId}`;
            const originalIndex = Number(await getAppMeta(controller.db, nextKey, 0));
            const clientId = `${controller.sessionId}_${hash}`;
            const meta = {
              client_id: clientId,
              upload_session_id: controller.sessionId,
              session_hash: `${controller.sessionId}:${hash}`,
              hash,
              original_index: originalIndex,
              original_filename: job.file.name || `photo_${originalIndex + 1}.jpg`,
              batch_index: job.batchIndex,
              selected_at: job.selectedAt,
              compressed_size: output.blob.size,
              width: output.width,
              height: output.height,
              mime: "image/jpeg",
              status: "queued",
              error: ""
            };
            await putPhoto(controller.db, meta, output.blob);
            await setAppMeta(controller.db, nextKey, originalIndex + 1);
            controller.compressedThisRun += 1;
            await renderState();
            await sendNextBatch();
          } catch (error) {
            await recordCompressionError(job, error);
            await renderState();
          }
        }
        controller.processing = false;
        await renderState();
        await sendNextBatch();
      }

      async function sendNextBatch() {
        if (controller.inFlight || disabled || !controller.db || !controller.sessionId) return;
        const rows = (await sessionMetas(controller.db, controller.sessionId)).filter(row => row.status === "queued");
        if (!rows.length) return;
        const selected = [];
        let bytes = 0;
        const maxEntries = Number(config.batch_size || 4);
        const maxBytes = Number(config.max_batch_bytes || 8 * 1024 * 1024);
        for (const row of rows) {
          if (selected.length >= maxEntries) break;
          if (selected.length && bytes + Number(row.compressed_size || 0) > maxBytes) break;
          selected.push(row);
          bytes += Number(row.compressed_size || 0);
        }
        if (!selected.length) selected.push(rows[0]);
        const entries = [];
        for (const row of selected) {
          const blob = await getBlob(controller.db, row.client_id);
          if (!blob) {
            await putMeta(controller.db, { ...row, status: "error", error: "Image locale introuvable" });
            continue;
          }
          entries.push({
            client_id: row.client_id,
            hash: row.hash,
            original_index: row.original_index,
            original_filename: row.original_filename,
            batch_index: row.batch_index,
            selected_at: row.selected_at,
            compressed_size: row.compressed_size,
            width: row.width,
            height: row.height,
            mime: row.mime,
            data_base64: bytesToBase64(new Uint8Array(await blob.arrayBuffer()))
          });
          await putMeta(controller.db, { ...row, status: "sending", error: "" });
        }
        if (!entries.length) {
          await renderState();
          return;
        }
        controller.inFlight = true;
        await renderState();
        controller.trigger("upload_batch", {
          drop_id: dropId,
          upload_session_id: controller.sessionId,
          batch_id: uuid("batch"),
          entries
        });
      }

      fileInput.onchange = async () => {
        const files = Array.from(fileInput.files || []);
        fileInput.value = "";
        if (!files.length || disabled) return;
        const batchKey = `next-batch:${controller.sessionId}`;
        const batchIndex = Number(await getAppMeta(controller.db, batchKey, 0));
        await setAppMeta(controller.db, batchKey, batchIndex + 1);
        const selectedAt = new Date().toISOString();
        for (const file of files) controller.pendingFiles.push({ file, batchIndex, selectedAt });
        controller.selectedThisRun += files.length;
        await renderState();
        processQueue();
      };
      selectButton.onclick = () => !disabled && fileInput.click();
      retryButton.onclick = async () => {
        const rows = await sessionMetas(controller.db, controller.sessionId);
        for (const row of rows.filter(item => item.status === "error")) {
          await putMeta(controller.db, { ...row, status: "queued", error: "" });
        }
        for (const row of rows.filter(item => item.status === "compression_error")) {
          const job = controller.failedFiles.get(row.client_id);
          if (job) controller.pendingFiles.push(job);
          await deleteMeta(controller.db, row.client_id);
        }
        await renderState();
        processQueue();
        sendNextBatch();
      };
      cancelButton.onclick = () => {
        if (!controller.sessionId) return;
        controller.trigger("cancel", { upload_session_id: controller.sessionId, token: uuid("cancel") });
      };
      analyzeButton.onclick = () => {
        if (!analyzeButton.disabled) controller.trigger("analyze", { upload_session_id: controller.sessionId });
      };

      initialize();
      return () => {
        for (const url of controller.previewUrls) URL.revokeObjectURL(url);
        controller.previewUrls = [];
      };
    }
    """
    _component = components_v2.component(
        "pokestock_browser_photo_upload",
        html=html,
        css=css,
        js=js,
        isolate_styles=True,
    )
    return _component


def _event(result, name: str):
    value = getattr(result, name, None) if result is not None else None
    if isinstance(value, list):
        return value[-1] if value else None
    return value


def render_browser_photo_upload(
    *,
    key: str,
    drop_id: str,
    upload_session_id: str = "",
    received_hashes: list[str] | None = None,
    ack: dict | None = None,
    cancel_token: str = "",
    disabled: bool = False,
    show_analyze_action: bool = True,
):
    component = _get_component()
    if component is None:
        return {}

    def _noop():
        return None

    result = component(
        key=key,
        data={
            "drop_id": drop_id,
            "upload_session_id": upload_session_id,
            "received_hashes": list(received_hashes or []),
            "ack": dict(ack or {}),
            "cancel_token": cancel_token,
            "disabled": disabled,
            "show_analyze_action": show_analyze_action,
            "max_dimension": 2048,
            "jpeg_quality": 0.89,
            "batch_size": 4,
            "max_batch_bytes": 8 * 1024 * 1024,
        },
        default={},
        width="stretch",
        height="content",
        on_upload_batch_change=_noop,
        on_cancel_change=_noop,
        on_analyze_change=_noop,
    )
    return {
        "upload_batch": _event(result, "upload_batch"),
        "cancel": _event(result, "cancel"),
        "analyze": _event(result, "analyze"),
    }
