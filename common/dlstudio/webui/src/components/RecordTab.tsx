import { useEffect, useRef, useState } from "preact/hooks";
import type { ProjectBeat } from "../api/types";
import { api, pollJob } from "../api/client";
import { MicRecorder, fileExtForMime } from "../lib/recorder";
import type { MeterLevels } from "../lib/recorder";
import { newTakeId } from "../lib/takes";
import type { SessionTake } from "../lib/takes";
import { fmtClock, fmtBytes } from "../lib/format";
import { LevelMeter } from "./LevelMeter";

interface Props {
  beat: ProjectBeat;
  takes: SessionTake[];
  addTake: (t: SessionTake) => void;
  updateTake: (id: string, patch: Partial<SessionTake>) => void;
  onAfterProcess: () => void;
}

export function RecordTab({
  beat,
  takes,
  addTake,
  updateTake,
  onAfterProcess,
}: Props) {
  const recRef = useRef<MicRecorder>(new MicRecorder());
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const timerRef = useRef<number>(0);
  const meterGate = useRef(0);

  const [micStatus, setMicStatus] = useState("mic not enabled");
  const [micReady, setMicReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState<MeterLevels | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedMic, setSelectedMic] = useState("");
  const [selectedCam, setSelectedCam] = useState("");
  const [cameraOn, setCameraOn] = useState(false);

  // Teardown on unmount.
  useEffect(() => {
    const rec = recRef.current;
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      rec.close();
      const cs = cameraStreamRef.current;
      if (cs) cs.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function refreshDevices() {
    try {
      if (!navigator.mediaDevices?.enumerateDevices) return;
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    refreshDevices();
  }, []);

  async function enableMic() {
    const rec = recRef.current;
    rec.onMeter = (lv) => {
      const now = performance.now();
      if (now - meterGate.current < 55) return; // ~18 fps
      meterGate.current = now;
      setLevels(lv);
    };
    try {
      setMicStatus("requesting mic…");
      await rec.open(selectedMic || undefined);
      setMicReady(true);
      setMicStatus("mic ready");
      await refreshDevices();
    } catch (e) {
      setMicReady(false);
      setMicStatus(`mic error: ${(e as Error).message}`);
    }
  }

  function startTimer() {
    const start = Date.now();
    setElapsed(0);
    timerRef.current = window.setInterval(() => {
      setElapsed((Date.now() - start) / 1000);
    }, 100);
  }
  function stopTimer() {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = 0;
  }

  async function toggleRecord() {
    const rec = recRef.current;
    if (!rec.ready) {
      await enableMic();
      if (!recRef.current.ready) return;
    }
    if (recording) {
      setRecording(false);
      stopTimer();
      try {
        const blob = await recRef.current.stopTake();
        await handleBlob(blob);
      } catch (e) {
        setMicStatus(`stop failed: ${(e as Error).message}`);
      }
    } else {
      recRef.current.beginTake();
      setRecording(true);
      startTimer();
    }
  }

  async function handleBlob(blob: Blob) {
    const ext = fileExtForMime(recRef.current.mimeType);
    const stamp = Math.floor(Date.now() / 1000);
    const filename = `${stamp}_${beat.id}_take.${ext}`;
    const id = newTakeId();
    const take: SessionTake = {
      id,
      beatId: beat.id,
      filename,
      url: URL.createObjectURL(blob),
      size: blob.size,
      createdAt: Date.now(),
      uploadState: "uploading",
      processState: "idle",
    };
    addTake(take);
    try {
      const res = await api.uploadTake(beat.id, blob, filename);
      updateTake(id, { uploadState: "uploaded", serverPath: res.path });
    } catch (e) {
      updateTake(id, {
        uploadState: "error",
        uploadError: (e as Error).message,
      });
    }
  }

  async function processTake(t: SessionTake) {
    if (!t.serverPath) return;
    updateTake(t.id, { processState: "running", processMessage: "starting…" });
    try {
      const { job_id } = await api.processTake({
        beat_id: beat.id,
        recording_path: t.serverPath,
      });
      const final = await pollJob(job_id, {
        onStatus: (s) =>
          updateTake(t.id, { processMessage: s.status }),
      });
      if (final.status === "done") {
        updateTake(t.id, { processState: "done", processMessage: "processed" });
        onAfterProcess();
      } else {
        updateTake(t.id, {
          processState: "error",
          processMessage: final.error || "process failed",
        });
      }
    } catch (e) {
      updateTake(t.id, {
        processState: "error",
        processMessage: (e as Error).message,
      });
    }
  }

  async function enableCamera() {
    try {
      if (cameraStreamRef.current) {
        cameraStreamRef.current.getTracks().forEach((tr) => tr.stop());
      }
      const video: MediaTrackConstraints | boolean = selectedCam
        ? { deviceId: { exact: selectedCam } }
        : true;
      const stream = await navigator.mediaDevices.getUserMedia({ video });
      cameraStreamRef.current = stream;
      setCameraOn(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      await refreshDevices();
    } catch (e) {
      setMicStatus(`camera error: ${(e as Error).message}`);
    }
  }

  function stopCamera() {
    const cs = cameraStreamRef.current;
    if (cs) cs.getTracks().forEach((tr) => tr.stop());
    cameraStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOn(false);
  }

  const mics = devices.filter((d) => d.kind === "audioinput");
  const cams = devices.filter((d) => d.kind === "videoinput");

  return (
    <div class="tab-body">
      <div class="record-grid">
        <div class="record-main">
          {beat.stage && <div class="stage-note">{beat.stage}</div>}
          <div class="vo-text" style={{ fontSize: "20px" }}>
            {beat.vo || "(no VO text)"}
          </div>

          <div class="device-row">
            <select
              class="device-select"
              value={selectedMic}
              onChange={(e) =>
                setSelectedMic((e.target as HTMLSelectElement).value)
              }
              title="Microphone"
            >
              <option value="">Default mic</option>
              {mics.map((d, i) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || `Mic ${i + 1}`}
                </option>
              ))}
            </select>
            <select
              class="device-select"
              value={selectedCam}
              onChange={(e) =>
                setSelectedCam((e.target as HTMLSelectElement).value)
              }
              title="Camera"
            >
              <option value="">Default camera</option>
              {cams.map((d, i) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || `Camera ${i + 1}`}
                </option>
              ))}
            </select>
            <button class="btn secondary sm" onClick={refreshDevices}>
              ↻ Devices
            </button>
          </div>

          {cameraOn && (
            <video
              ref={videoRef}
              class="camera-preview"
              autoPlay
              playsInline
              muted
            />
          )}

          <div class="rec-controls">
            {!micReady && (
              <button class="btn secondary" onClick={enableMic}>
                🎙 Enable mic
              </button>
            )}
            <button
              class={"btn record" + (recording ? " recording" : "")}
              onClick={toggleRecord}
            >
              {recording ? "■ Stop & save" : "● Record"}
            </button>
            {!cameraOn ? (
              <button class="btn secondary" onClick={enableCamera}>
                📷 Camera
              </button>
            ) : (
              <button class="btn secondary" onClick={stopCamera}>
                ■ Stop camera
              </button>
            )}
            <span class="timer">{fmtClock(elapsed)}</span>
            <span class="spacer" style={{ flex: 1 }} />
            <span class="action-status">{micStatus}</span>
          </div>

          <div class="meters">
            <LevelMeter label="RMS" db={levels?.rmsDb ?? null} />
            <LevelMeter label="Peak" db={levels?.peakDb ?? null} />
          </div>
        </div>

        <div class="takes">
          <h3>Session takes · {beat.id}</h3>
          {takes.length === 0 ? (
            <div class="empty">No takes yet — hit Record.</div>
          ) : (
            takes
              .slice()
              .sort((a, b) => b.createdAt - a.createdAt)
              .map((t) => (
                <div class="take" key={t.id}>
                  <div class="name">{t.filename}</div>
                  <div class="meta">
                    {fmtBytes(t.size)} ·{" "}
                    {t.uploadState === "uploading"
                      ? "uploading…"
                      : t.uploadState === "error"
                        ? `upload failed: ${t.uploadError}`
                        : "uploaded"}
                  </div>
                  <audio controls preload="none" src={t.url} />
                  <div class="take-actions">
                    <button
                      class="btn secondary sm"
                      disabled={
                        t.uploadState !== "uploaded" ||
                        t.processState === "running"
                      }
                      onClick={() => processTake(t)}
                    >
                      {t.processState === "running"
                        ? "Processing…"
                        : "Process take"}
                    </button>
                    <span class="take-status">{t.processMessage || ""}</span>
                  </div>
                </div>
              ))
          )}
        </div>
      </div>
    </div>
  );
}
