import { useEffect, useRef, useState } from "preact/hooks";
import type { ProjectBeat } from "../api/types";
import { api, pollJob } from "../api/client";
import { MicRecorder, fileExtForMime } from "../lib/recorder";
import type { MeterLevels } from "../lib/recorder";
import { newTakeId } from "../lib/takes";
import type { SessionTake, VoiceTakeMetadata } from "../lib/takes";
import { fmtClock, fmtBytes } from "../lib/format";
import { LevelMeter } from "./LevelMeter";
import { RecordingPrompter } from "./RecordingPrompter";

interface Props {
  beat: ProjectBeat;
  takes: SessionTake[];
  addTake: (t: SessionTake) => void;
  updateTake: (id: string, patch: Partial<SessionTake>) => void;
  onAfterProcess: () => void;
  scriptApproved?: boolean;
}

const COUNTDOWN_SECONDS = 3;
const ROOM_TONE_SECONDS = 2;
const POST_ROLL_SECONDS = 1;

export function RecordTab({
  beat,
  takes,
  addTake,
  updateTake,
  onAfterProcess,
  scriptApproved = true,
}: Props) {
  const recRef = useRef<MicRecorder>(new MicRecorder());
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const timerRef = useRef<number>(0);
  const postRollTimerRef = useRef<number>(0);
  const elapsedRef = useRef(0);
  const stopRequestedRef = useRef<number | null>(null);
  const meterGate = useRef(0);
  // The beat a take belongs to is pinned when recording STARTS (defect 0.7):
  // `beat` is a live prop — reading it at stop/upload time attributed the
  // take to whatever beat was selected by then, not the one recorded.
  const takeBeatIdRef = useRef<string | null>(null);
  // In-flight process-take pollers, aborted when the beat changes or the tab
  // unmounts so their pollJob loops don't leak. (L2)
  const pollAborters = useRef<Set<AbortController>>(new Set());

  const [micStatus, setMicStatus] = useState("mic not enabled");
  const [micReady, setMicReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [postRolling, setPostRolling] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState<MeterLevels | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedMic, setSelectedMic] = useState("");
  const [selectedCam, setSelectedCam] = useState("");
  const [cameraOn, setCameraOn] = useState(false);
  const [promptText, setPromptText] = useState(beat.vo || "");

  // Stop the current take (if any) and save it to the beat captured at
  // record start. Idempotent — the ref hand-off makes exactly one caller
  // win, so the stop button, a beat switch, and unmount can all call it.
  // Kept in a ref so the []-deps teardown always sees the latest closure.
  async function stopAndSave(): Promise<void> {
    const rec = recRef.current;
    const beatId = takeBeatIdRef.current;
    takeBeatIdRef.current = null;
    if (!beatId || !rec.recording) return;
    if (postRollTimerRef.current) clearTimeout(postRollTimerRef.current);
    postRollTimerRef.current = 0;
    const stoppedAt = elapsedRef.current;
    const stopRequestedAt = stopRequestedRef.current ?? stoppedAt;
    const recordingMetadata: VoiceTakeMetadata = {
      schema: "devlog.voice_take",
      version: 1,
      countdown_seconds: COUNTDOWN_SECONDS,
      room_tone_seconds: ROOM_TONE_SECONDS,
      speech_start_seconds: COUNTDOWN_SECONDS + ROOM_TONE_SECONDS,
      stop_requested_seconds: stopRequestedAt,
      post_roll_end_seconds: stoppedAt,
      post_roll_target_seconds: POST_ROLL_SECONDS,
      post_roll_completed: stoppedAt - stopRequestedAt >= POST_ROLL_SECONDS - 0.1,
      completed_lead_in: stopRequestedAt >= COUNTDOWN_SECONDS + ROOM_TONE_SECONDS,
    };
    stopRequestedRef.current = null;
    setRecording(false);
    setPostRolling(false);
    stopTimer();
    try {
      const blob = await rec.stopTake();
      await handleBlob(blob, beatId, recordingMetadata);
    } catch (e) {
      setMicStatus(`stop failed: ${(e as Error).message}`);
    }
  }
  const stopAndSaveRef = useRef(stopAndSave);
  stopAndSaveRef.current = stopAndSave;

  // Teardown on unmount. A recording in flight is SAVED first (defect 0.7:
  // switching tabs used to rec.close() and silently drop the take), then the
  // recorder/camera are released.
  useEffect(() => {
    const rec = recRef.current;
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (postRollTimerRef.current) clearTimeout(postRollTimerRef.current);
      const salvage = rec.recording
        ? stopAndSaveRef.current()
        : Promise.resolve();
      void salvage.finally(() => rec.close());
      const cs = cameraStreamRef.current;
      if (cs) cs.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // When the active beat switches (this component is reused across beats):
  // a recording in flight is stopped and saved TO THE BEAT IT STARTED ON
  // (defect 0.7 — switching required a stop; this is that stop, without
  // losing the take), and in-flight process-take polls are aborted. (L2)
  useEffect(() => {
    setPromptText(beat.vo || "");
    const aborters = pollAborters.current;
    return () => {
      void stopAndSaveRef.current();
      aborters.forEach((a) => a.abort());
      aborters.clear();
    };
  }, [beat.id, beat.vo]);

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
    elapsedRef.current = 0;
    setElapsed(0);
    timerRef.current = window.setInterval(() => {
      const current = (Date.now() - start) / 1000;
      elapsedRef.current = current;
      setElapsed(current);
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
      if (postRolling) return;
      stopRequestedRef.current = elapsedRef.current;
      setPostRolling(true);
      postRollTimerRef.current = window.setTimeout(() => {
        elapsedRef.current = Math.max(
          elapsedRef.current,
          (stopRequestedRef.current ?? 0) + POST_ROLL_SECONDS,
        );
        void stopAndSaveRef.current();
      }, POST_ROLL_SECONDS * 1000);
    } else {
      setPromptText(beat.vo || "");
      recRef.current.beginTake();
      takeBeatIdRef.current = beat.id; // pin the take's beat at START (0.7)
      stopRequestedRef.current = null;
      setPostRolling(false);
      setRecording(true);
      startTimer();
    }
  }

  async function handleBlob(
    blob: Blob,
    beatId: string,
    recordingMetadata: VoiceTakeMetadata,
  ) {
    // `beatId` is the beat captured at record start — NEVER the live
    // `beat.id` prop, which may have changed mid-take (defect 0.7).
    const ext = fileExtForMime(recRef.current.mimeType);
    const stamp = Math.floor(Date.now() / 1000);
    const filename = `${stamp}_${beatId}_take.${ext}`;
    const id = newTakeId();
    const take: SessionTake = {
      id,
      beatId,
      filename,
      url: URL.createObjectURL(blob),
      size: blob.size,
      createdAt: Date.now(),
      uploadState: "uploading",
      processState: "idle",
      recordingMetadata,
    };
    addTake(take);
    try {
      const res = await api.uploadTake(beatId, blob, filename, recordingMetadata);
      updateTake(id, {
        uploadState: "uploaded",
        serverPath: res.path,
        metadataPath: res.metadata_path,
      });
    } catch (e) {
      updateTake(id, {
        uploadState: "error",
        uploadError: (e as Error).message,
      });
    }
  }

  async function processTake(t: SessionTake) {
    if (!t.serverPath) return;
    const ctrl = new AbortController();
    pollAborters.current.add(ctrl);
    updateTake(t.id, { processState: "running", processMessage: "starting…" });
    try {
      const { job_id } = await api.processTake({
        beat_id: t.beatId, // the take's own beat, pinned at record start (0.7)
        recording_path: t.serverPath,
      });
      const final = await pollJob(job_id, {
        signal: ctrl.signal,
        onStatus: (s) => updateTake(t.id, { processMessage: s.status }),
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
      if (ctrl.signal.aborted) return; // beat switch / unmount — drop silently
      updateTake(t.id, {
        processState: "error",
        processMessage: (e as Error).message,
      });
    } finally {
      pollAborters.current.delete(ctrl);
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
          <RecordingPrompter
            text={recording ? promptText : beat.vo || ""}
            elapsed={elapsed}
            recording={recording}
            countdownSeconds={COUNTDOWN_SECONDS}
            roomToneSeconds={ROOM_TONE_SECONDS}
            postRolling={postRolling}
          />

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
            {!scriptApproved && !recording && (
              <span class="approval-warning">
                Approve the current script before recording.
              </span>
            )}
            {!micReady && (
              <button class="btn secondary" onClick={enableMic}>
                🎙 Enable mic
              </button>
            )}
            <button
              class={"btn record" + (recording ? " recording" : "")}
              onClick={toggleRecord}
              disabled={postRolling || (!scriptApproved && !recording)}
            >
              {postRolling
                ? "… Saving post-roll"
                : recording
                  ? "■ Stop & save"
                  : "● Record"}
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
                  {t.recordingMetadata && (
                    !t.recordingMetadata.completed_lead_in
                    || !t.recordingMetadata.post_roll_completed
                  ) && (
                    <div class="approval-warning">
                      Incomplete clean handles · prefer recapture or guarded trim
                    </div>
                  )}
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
