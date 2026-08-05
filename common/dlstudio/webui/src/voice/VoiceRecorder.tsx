import { useEffect, useRef, useState } from "preact/hooks";
import { studioV3 } from "../api/v3.client";
import type { components } from "../api/v3.gen";
import { deleteVoiceDraft, loadVoiceDraft, saveVoiceDraft } from "./draftStore";

type RecorderContext = components["schemas"]["VoiceRecorderContext"];
type RecorderPhase = "idle" | "countdown" | "recording" | "preview" | "saving";
const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatTime(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function blobUrl(take: RecorderContext["takes"][number]): string {
  return `/api/v3/blobs/${take.blob.sha256}?size=${take.blob.size}`;
}

function approvalLabel(take: RecorderContext["takes"][number]): string {
  switch (take.approval_status) {
    case "pending": return "Ожидает проверки";
    case "validated": return "Проверен, ожидает одобрения";
    case "approved": return "Одобрен";
    case "rejected": return take.approval_reason ? `Отклонён: ${take.approval_reason}` : "Отклонён";
  }
}

export function VoiceRecorder() {
  const confirmationRef = useRef<HTMLDivElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const animationRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef(0);
  const recordedAtRef = useRef("");
  const previewUrlRef = useRef<string | null>(null);
  const previewIdentityRef = useRef<Pick<RecorderContext, "production_id" | "script_ref"> | null>(null);
  const [context, setContext] = useState<RecorderContext | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [phase, setPhase] = useState<RecorderPhase>("idle");
  const [permission, setPermission] = useState<"unknown" | "ready" | "denied">("unknown");
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [restoredDraft, setRestoredDraft] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [approvingAssetId, setApprovingAssetId] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");

  function confirmCanonical(
    action: "Saved" | "Approved",
    next: RecorderContext,
    assetId?: string,
  ) {
    const take = assetId
      ? next.takes.find((item) => item.asset_id === assetId)
      : next.takes[0];
    if (!take) return;
    setConfirmation(
      `${action} take ${take.take_id}; state revision ${next.state_revision}; ` +
      `${take.current_script ? "current script" : "stale script"}; ` +
      `${formatTime(take.duration_ns / 1_000_000)}; ${take.approval_status}.`,
    );
  }

  async function loadContext() {
    const result = await studioV3.GET("/api/v3/voice");
    if (!result.data) throw new Error("Voice API returned no context.");
    setContext(result.data);
    return result.data;
  }

  async function approveTake(assetId: string) {
    if (!context) return;
    setApprovingAssetId(assetId);
    setError(null);
    try {
      const result = await studioV3.POST(
        "/api/v3/voice/takes/{asset_id}/approve",
        {
          params: { path: { asset_id: assetId } },
          body: {
            expected_revision: context.state_revision,
            approved_at: new Date().toISOString(),
            expected_production_id: context.production_id,
            expected_script_ref: context.script_ref,
          },
        },
      );
      if (result.error) {
        const detail = "detail" in result.error ? result.error.detail : result.error;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      if (!result.data) {
        throw new Error("Studio did not return the approved take.");
      }
      setContext(result.data);
      confirmCanonical("Approved", result.data, assetId);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setApprovingAssetId(null);
    }
  }

  async function refreshDevices() {
    const available = await navigator.mediaDevices.enumerateDevices();
    const microphones = available.filter((device) => device.kind === "audioinput");
    setDevices(microphones);
    if (!deviceId && microphones[0]) setDeviceId(microphones[0].deviceId);
  }

  function stopMeter() {
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setLevel(0);
  }

  function startMeter(stream: MediaStream) {
    stopMeter();
    const audioContext = new AudioContext();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.78;
    audioContext.createMediaStreamSource(stream).connect(analyser);
    const values = new Uint8Array(analyser.fftSize);
    audioContextRef.current = audioContext;
    const sample = () => {
      analyser.getByteTimeDomainData(values);
      let sum = 0;
      for (const value of values) {
        const centered = (value - 128) / 128;
        sum += centered * centered;
      }
      setLevel(Math.min(1, Math.sqrt(sum / values.length) * 5.5));
      animationRef.current = requestAnimationFrame(sample);
    };
    sample();
  }

  async function prepareMicrophone() {
    setError(null);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      setPermission("ready");
      startMeter(stream);
      await refreshDevices();
    } catch (cause) {
      setPermission("denied");
      setError("Не удалось открыть микрофон. Разрешите доступ в браузере и попробуйте снова.");
      throw cause;
    }
  }

  function clearPreview() {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setPreviewUrl(null);
    setPreviewBlob(null);
    previewIdentityRef.current = null;
    setRestoredDraft(false);
    setElapsed(0);
    setPhase("idle");
  }

  async function startRecording() {
    setError(null);
    if (!context) return;
    if (!streamRef.current) {
      try { await prepareMicrophone(); } catch { return; }
    }
    clearPreview();
    setPhase("countdown");
    for (const value of [3, 2, 1]) {
      setCountdown(value);
      await new Promise((resolve) => setTimeout(resolve, 650));
    }
    setCountdown(null);
    const stream = streamRef.current;
    if (!stream) return;
    const mimeType = MIME_CANDIDATES.find((candidate) => MediaRecorder.isTypeSupported(candidate));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (event) => { if (event.data.size > 0) chunks.push(event.data); };
    recorder.onstop = () => {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const url = URL.createObjectURL(blob);
      const takeElapsed = Math.max(1, Math.round(performance.now() - startedAtRef.current));
      previewUrlRef.current = url;
      setElapsed(takeElapsed);
      setPreviewBlob(blob);
      setPreviewUrl(url);
      setRestoredDraft(false);
      setPhase("preview");
      void saveVoiceDraft({
        blob,
        elapsedMs: takeElapsed,
        recordedAt: recordedAtRef.current,
        productionId: context.production_id,
        scriptRef: context.script_ref,
      }).catch(() => setError("Дубль записан, но браузер не смог защитить его от перезагрузки. Сохраните его сейчас."));
    };
    mediaRecorderRef.current = recorder;
    previewIdentityRef.current = {
      production_id: context.production_id,
      script_ref: context.script_ref,
    };
    recordedAtRef.current = new Date().toISOString();
    startedAtRef.current = performance.now();
    setElapsed(0);
    setPhase("recording");
    recorder.start(250);
    timerRef.current = setInterval(() => setElapsed(Math.round(performance.now() - startedAtRef.current)), 100);
  }

  function stopRecording() {
    if (mediaRecorderRef.current?.state === "recording") mediaRecorderRef.current.stop();
  }

  async function saveTake() {
    const identity = previewIdentityRef.current;
    if (!previewBlob || !context || !identity) return;
    setPhase("saving");
    setError(null);
    try {
      const response = await fetch(`/api/v3/voice/takes?expected_revision=${context.state_revision}`, {
        method: "POST",
        headers: {
          "Content-Type": previewBlob.type || "audio/webm",
          "X-Recorded-At": recordedAtRef.current,
          "X-Duration-Ms": String(Math.max(1, elapsed)),
          "X-Production-Id": identity.production_id,
          "X-Script-Sha256": identity.script_ref.sha256,
          "X-Script-Size": String(identity.script_ref.size),
        },
        body: previewBlob,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? `Studio returned ${response.status}.`);
      }
      const next = (await response.json()) as RecorderContext;
      setContext(next);
      await deleteVoiceDraft(identity.production_id, identity.script_ref).catch(() => undefined);
      clearPreview();
      confirmCanonical("Saved", next);
    } catch (cause) {
      setError(errorMessage(cause));
      setPhase("preview");
    }
  }

  useEffect(() => {
    if (confirmation) confirmationRef.current?.focus();
  }, [confirmation]);

  useEffect(() => {
    void loadContext()
      .then(async (loadedContext) => {
        const draft = await loadVoiceDraft(
          loadedContext.production_id,
          loadedContext.script_ref,
        );
        if (!draft || previewUrlRef.current) return;
        const url = URL.createObjectURL(draft.blob);
        previewUrlRef.current = url;
        recordedAtRef.current = draft.recordedAt;
        previewIdentityRef.current = {
          production_id: draft.productionId,
          script_ref: draft.scriptRef,
        };
        setPreviewBlob(draft.blob);
        setPreviewUrl(url);
        setElapsed(draft.elapsedMs);
        setRestoredDraft(true);
        setPhase("preview");
      })
      .catch((cause) => setError(errorMessage(cause)));
    if (!navigator.mediaDevices || !window.MediaRecorder) setError("Этот браузер не поддерживает запись с микрофона.");
    else void refreshDevices().catch(() => undefined);
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      stopMeter();
      if (timerRef.current) clearInterval(timerRef.current);
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  return (
    <section class="voice-studio" aria-labelledby="voice-title">
      <div
        class="voice-confirmation"
        role="status"
        aria-live="polite"
        tabIndex={-1}
        ref={confirmationRef}
      >
        {confirmation}
      </div>
      <div class="voice-project-bar">
        <div><p class="eyebrow">ТЕКУЩИЙ ПРОЕКТ</p><h2 id="voice-title">{context?.production_id ?? "Загрузка проекта…"}</h2></div>
        <div class={`mic-status ${permission}`}><span aria-hidden="true" />{permission === "ready" ? "Микрофон готов" : permission === "denied" ? "Нет доступа" : "Микрофон не подключён"}</div>
      </div>
      <div class="voice-layout">
        <div class="voice-main-column">
          <article class="script-card">
            <div class="script-meta"><span>ТЕКСТ ОЗВУЧКИ</span><span>{context?.script_text.trim().split(/\s+/).length ?? 0} слов</span></div>
            <div class="teleprompter">{(context?.script_text ?? "Текст загружается…").split(/\n\n+/).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</div>
          </article>
          <section class={`recorder-console ${phase === "recording" ? "is-recording" : ""}`}>
            <div class="meter-header"><span>{phase === "recording" ? "ИДЁТ ЗАПИСЬ" : "УРОВЕНЬ МИКРОФОНА"}</span><strong>{formatTime(elapsed)}</strong></div>
            <div class="level-track" aria-label={`Уровень микрофона ${Math.round(level * 100)}%`}><span style={{ width: `${Math.max(2, level * 100)}%` }} /></div>
            <label class="device-field"><span>Микрофон</span><select value={deviceId} disabled={phase === "recording" || phase === "countdown"} onChange={(event) => { setDeviceId(event.currentTarget.value); if (permission === "ready") void prepareMicrophone(); }}>
              {devices.length === 0 && <option value="">Системный микрофон</option>}
              {devices.map((device, index) => <option value={device.deviceId} key={device.deviceId}>{device.label || `Микрофон ${index + 1}`}</option>)}
            </select></label>
            {countdown !== null && <div class="countdown" aria-live="assertive">{countdown}</div>}
            {previewUrl && <div class="take-preview"><div><span>{restoredDraft ? "ВОССТАНОВЛЕННЫЙ ЧЕРНОВИК" : "НОВЫЙ ДУБЛЬ"}</span><strong>{formatTime(elapsed)}</strong></div><audio controls preload="metadata" src={previewUrl} /></div>}
            {error && <div class="recorder-error" role="alert">{error}</div>}
            <div class="recorder-actions">
              {permission !== "ready" && phase === "idle" && <button class="secondary-action" onClick={() => void prepareMicrophone()}>Подключить микрофон</button>}
              {(phase === "idle" || phase === "preview") && <button class="record-action" onClick={() => void startRecording()} disabled={!context}><span aria-hidden="true" />{previewBlob ? "Перезаписать" : "Записать дубль"}</button>}
              {phase === "recording" && <button class="stop-action" onClick={stopRecording}><span aria-hidden="true" /> Остановить</button>}
              {previewBlob && phase === "preview" && <button class="save-action" onClick={() => void saveTake()}>Сохранить дубль</button>}
              {phase === "saving" && <button class="save-action" disabled>Сохраняю оригинал…</button>}
            </div>
            <p class="preservation-note">Каждый сохранённый дубль остаётся в проекте. Оригиналы не перезаписываются.</p>
          </section>
        </div>
        <aside class="takes-panel">
          <div class="takes-heading"><div><p class="eyebrow">ЗАПИСИ</p><h2>Дубли</h2></div><span class="take-count">{context?.takes.length ?? 0}</span></div>
          {!context?.takes.length ? <div class="empty-takes"><span>01</span><p>Первый дубль появится здесь сразу после сохранения.</p></div> : <ol class="take-list">
            {context.takes.map((take, index) => <li class="saved-take" key={take.asset_id}>
              <div class="take-title"><strong>Дубль {context.takes.length - index}</strong><span>{formatDate(take.recorded_at)}</span></div>
              <audio controls preload="metadata" src={blobUrl(take)} />
              <div class="take-facts">
                <span>{formatTime(take.duration_ns / 1_000_000)}</span>
                <span>{take.codec?.toUpperCase() ?? take.format_name}</span>
                <span>Канонически сохранён</span>
                <span class={take.current_script ? "script-match" : "script-old"}>{take.current_script ? "Текущий текст" : "Старый текст"}</span>
                <span class={take.approval_status === "approved" ? "take-approved" : take.approval_status === "rejected" ? "take-rejected" : "take-pending"}>
                  {approvalLabel(take)}
                </span>
                <span class={take.referenced_by_timeline ? "take-selected" : "take-unselected"}>
                  {take.referenced_by_timeline ? "В текущем TimelineIR" : "Не добавлен в TimelineIR"}
                </span>
              </div>
              <code class="take-asset-id">{take.asset_id}</code>
              {(take.approval_status === "pending" || take.approval_status === "validated") && take.current_script && (
                <button
                  class="secondary-action use-take"
                  disabled={approvingAssetId !== null}
                  onClick={() => void approveTake(take.asset_id)}
                >
                  {approvingAssetId === take.asset_id ? "Одобряю…" : "Использовать этот дубль"}
                </button>
              )}
            </li>)}
          </ol>}
        </aside>
      </div>
    </section>
  );
}
