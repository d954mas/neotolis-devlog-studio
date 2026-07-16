import type { IRBeat, ProjectBeat } from "../api/types";
import { api } from "../api/client";
import { Karaoke } from "./Karaoke";

interface Props {
  beat: ProjectBeat;
  irBeat: IRBeat | null;
  /** Rendered draft mp4 path, if one exists. */
  previewPath: string | null;
  /** Cache-buster set once per completed render (see app.tsx). */
  previewToken?: number;
}

export function ScriptTab({ beat, irBeat, previewPath, previewToken }: Props) {
  const words = irBeat?.words ?? [];
  const audioPath = beat.audio || irBeat?.audio || "";
  const canKaraoke = !!audioPath && words.length > 0;
  // Stable src: the token changes only when a new render lands, so the video
  // isn't refetched on every unrelated re-render (Date.now() per pass did).
  const previewSrc = previewPath
    ? api.fileUrl(previewPath) + (previewToken ? "&t=" + previewToken : "")
    : null;

  return (
    <div class="tab-body">
      {previewPath && (
        <div class="preview">
          <video controls preload="metadata" src={previewSrc ?? undefined} />
          <div class="meta">{previewPath}</div>
        </div>
      )}

      {beat.stage && <div class="stage-note">{beat.stage}</div>}

      {canKaraoke ? (
        <Karaoke audioPath={audioPath} words={words} />
      ) : (
        <>
          <div class="vo-text">{beat.vo || "(no VO text)"}</div>
          <p class="hint">
            {audioPath
              ? "No word timings in the IR yet — showing plain script."
              : "Karaoke unlocks once a take is recorded and processed (VO audio + word timings)."}
          </p>
        </>
      )}
    </div>
  );
}
