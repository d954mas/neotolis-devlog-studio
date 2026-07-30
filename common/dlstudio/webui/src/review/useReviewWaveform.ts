import { useCallback, useEffect, useState } from "preact/hooks";

import { studioV3 } from "../api/v3.client";
import type { BlobRef } from "./types";

const MAX_CACHED_WAVEFORMS = 12;

export type ReviewWaveformData = {
  artifact: BlobRef;
  durationNs: number;
  hasAudio: boolean;
  peaksMilli: readonly number[];
  sampleCount: number;
};

export type ReviewWaveformStatus =
  | "loading"
  | "ready"
  | "no_audio"
  | "error";

export type ReviewWaveformState = {
  status: ReviewWaveformStatus;
  data: ReviewWaveformData | null;
  error: string | null;
  retry: () => void;
};

type LoadState = Omit<ReviewWaveformState, "retry">;
type KeyedLoadState = LoadState & { key: string };

const waveformCache = new Map<string, ReviewWaveformData>();
const inFlightWaveforms = new Map<
  string,
  Promise<ReviewWaveformData>
>();

function waveformKey(
  artifact: BlobRef,
  expectedDurationNs: number,
  sampleCount: number,
): string {
  return `${artifact.sha256}:${artifact.size}:${expectedDurationNs}:${sampleCount}`;
}

function cachedWaveform(key: string): ReviewWaveformData | undefined {
  const cached = waveformCache.get(key);
  if (!cached) return undefined;
  waveformCache.delete(key);
  waveformCache.set(key, cached);
  return cached;
}

function cacheWaveform(key: string, waveform: ReviewWaveformData): void {
  waveformCache.delete(key);
  waveformCache.set(key, waveform);
  while (waveformCache.size > MAX_CACHED_WAVEFORMS) {
    const oldestKey = waveformCache.keys().next().value as string | undefined;
    if (oldestKey === undefined) break;
    waveformCache.delete(oldestKey);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function validateWaveform(
  value: unknown,
  expectedArtifact: BlobRef,
  expectedDurationNs: number,
  expectedSampleCount: number,
): ReviewWaveformData {
  if (!isRecord(value) || !isRecord(value.artifact)) {
    throw new Error("Некорректный ответ с формой звука.");
  }

  const artifact = value.artifact;
  if (
    artifact.sha256 !== expectedArtifact.sha256 ||
    artifact.size !== expectedArtifact.size
  ) {
    throw new Error("Форма звука относится к другой версии видео.");
  }

  if (
    value.sample_count !== expectedSampleCount ||
    !Number.isInteger(value.sample_count)
  ) {
    throw new Error("Форма звука имеет неожиданную детализацию.");
  }

  if (
    typeof value.duration_ns !== "number" ||
    !Number.isSafeInteger(value.duration_ns) ||
    value.duration_ns <= 0 ||
    typeof value.has_audio !== "boolean" ||
    !Array.isArray(value.peaks_milli) ||
    value.peaks_milli.length !== expectedSampleCount
  ) {
    throw new Error("Некорректный ответ с формой звука.");
  }
  if (value.duration_ns !== expectedDurationNs) {
    throw new Error("Форма звука относится к другой длительности видео.");
  }

  const peaksMilli: number[] = [];
  for (const peak of value.peaks_milli) {
    if (!Number.isInteger(peak) || peak < 0 || peak > 1000) {
      throw new Error("Некорректные значения формы звука.");
    }
    peaksMilli.push(peak);
  }

  return {
    artifact: {
      sha256: expectedArtifact.sha256,
      size: expectedArtifact.size,
    },
    durationNs: value.duration_ns,
    hasAudio: value.has_audio,
    peaksMilli,
    sampleCount: expectedSampleCount,
  };
}

async function requestWaveform(
  artifact: BlobRef,
  expectedDurationNs: number,
  sampleCount: number,
): Promise<ReviewWaveformData> {
  const key = waveformKey(artifact, expectedDurationNs, sampleCount);
  const cached = cachedWaveform(key);
  if (cached) return cached;

  const pending = inFlightWaveforms.get(key);
  if (pending) return pending;

  const request = studioV3
    .GET("/api/v3/review/artifacts/{sha256}/waveform", {
      params: {
        path: { sha256: artifact.sha256 },
        query: { size: artifact.size, samples: sampleCount },
      },
    })
    .then((result) => {
      if (!result.data) {
        throw new Error("Не удалось загрузить форму звука.");
      }
      const waveform = validateWaveform(
        result.data,
        artifact,
        expectedDurationNs,
        sampleCount,
      );
      cacheWaveform(key, waveform);
      return waveform;
    });

  inFlightWaveforms.set(key, request);
  const clearRequest = () => {
    if (inFlightWaveforms.get(key) === request) {
      inFlightWaveforms.delete(key);
    }
  };
  void request.then(clearRequest, clearRequest);
  return request;
}

function stateFor(
  key: string,
  waveform: ReviewWaveformData,
): KeyedLoadState {
  return {
    key,
    status: waveform.hasAudio ? "ready" : "no_audio",
    data: waveform,
    error: null,
  };
}

export function useReviewWaveform(
  artifact: BlobRef,
  expectedDurationNs: number,
  sampleCount = 1024,
): ReviewWaveformState {
  const key = waveformKey(artifact, expectedDurationNs, sampleCount);
  const [retryToken, setRetryToken] = useState(0);
  const [state, setState] = useState<KeyedLoadState>(() => {
    const cached = cachedWaveform(key);
    return cached
      ? stateFor(key, cached)
      : { key, status: "loading", data: null, error: null };
  });

  useEffect(() => {
    let active = true;
    const cached = cachedWaveform(key);
    if (cached) {
      setState(stateFor(key, cached));
      return () => {
        active = false;
      };
    }

    setState({ key, status: "loading", data: null, error: null });
    if (
      !Number.isInteger(sampleCount) ||
      sampleCount < 256 ||
      sampleCount > 8192 ||
      !Number.isSafeInteger(expectedDurationNs) ||
      expectedDurationNs <= 0
    ) {
      setState({
        key,
        status: "error",
        data: null,
        error: "Некорректные параметры формы звука.",
      });
      return () => {
        active = false;
      };
    }

    void requestWaveform(artifact, expectedDurationNs, sampleCount)
      .then((waveform) => {
        if (active) setState(stateFor(key, waveform));
      })
      .catch(() => {
        if (active) {
          setState({
            key,
            status: "error",
            data: null,
            error: "Форма звука сейчас недоступна.",
          });
        }
      });

    return () => {
      active = false;
    };
  }, [
    artifact.sha256,
    artifact.size,
    expectedDurationNs,
    key,
    retryToken,
    sampleCount,
  ]);

  const retry = useCallback(() => {
    waveformCache.delete(key);
    setRetryToken((value) => value + 1);
  }, [key]);

  if (state.key !== key) {
    return {
      status: "loading",
      data: null,
      error: null,
      retry,
    };
  }
  return { ...state, retry };
}
