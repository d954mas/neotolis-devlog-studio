// MediaRecorder + WebAudio level metering, extracted from the legacy studio's
// inline recorder so components stay declarative. One instance owns the mic
// stream, the MediaRecorder, and the AnalyserNode meter loop.

export interface MeterLevels {
  /** RMS level in dBFS (~ -60..0). */
  rmsDb: number;
  /** Decaying peak level in dBFS. */
  peakDb: number;
}

function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  const MR = window.MediaRecorder;
  if (MR && typeof MR.isTypeSupported === "function") {
    for (const c of candidates) {
      if (MR.isTypeSupported(c)) return c;
    }
  }
  return "audio/webm";
}

export class MicRecorder {
  stream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private raf = 0;
  private chunks: Blob[] = [];
  private peak = 0;
  mimeType = "audio/webm";

  onMeter: ((levels: MeterLevels) => void) | null = null;

  get ready(): boolean {
    return this.mediaRecorder != null;
  }

  get recording(): boolean {
    return this.mediaRecorder?.state === "recording";
  }

  /** Acquire the mic, wire up MediaRecorder + the analyser meter loop. */
  async open(deviceId?: string): Promise<void> {
    this.close();
    const audio: MediaTrackConstraints | boolean = deviceId
      ? { deviceId: { exact: deviceId } }
      : true;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio });
    this.mimeType = pickMimeType();
    this.mediaRecorder = new MediaRecorder(this.stream, {
      mimeType: this.mimeType,
    });
    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) this.chunks.push(e.data);
    };

    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    this.audioCtx = new Ctx();
    const src = this.audioCtx.createMediaStreamSource(this.stream);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 1024;
    src.connect(this.analyser);
    this.peak = 0;
    this.meterLoop();
  }

  private meterLoop = () => {
    const analyser = this.analyser;
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    let localPeak = 0;
    for (let i = 0; i < data.length; i++) {
      const v = Math.abs(data[i]);
      sum += v * v;
      if (v > localPeak) localPeak = v;
    }
    const rms = Math.sqrt(sum / data.length);
    this.peak = Math.max(this.peak * 0.95, localPeak);
    const rmsDb = 20 * Math.log10(Math.max(rms, 1e-6));
    const peakDb = 20 * Math.log10(Math.max(this.peak, 1e-6));
    this.onMeter?.({ rmsDb, peakDb });
    this.raf = requestAnimationFrame(this.meterLoop);
  };

  beginTake(): void {
    if (!this.mediaRecorder) throw new Error("recorder not open");
    this.chunks = [];
    this.mediaRecorder.start();
  }

  /** Stop the current take and resolve with the recorded blob. */
  stopTake(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      const mr = this.mediaRecorder;
      if (!mr || mr.state !== "recording") {
        reject(new Error("not recording"));
        return;
      }
      mr.onstop = () => {
        resolve(new Blob(this.chunks, { type: this.mimeType }));
      };
      mr.stop();
    });
  }

  /** Tear down stream, recorder, and meter loop. */
  close(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (this.mediaRecorder && this.mediaRecorder.state === "recording") {
      try {
        this.mediaRecorder.stop();
      } catch {
        /* noop */
      }
    }
    this.mediaRecorder = null;
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    this.analyser = null;
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}

export function fileExtForMime(mime: string): string {
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "m4a";
  return "webm";
}
