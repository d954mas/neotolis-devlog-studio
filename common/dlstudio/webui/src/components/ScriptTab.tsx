import type { IRBeat, ProjectBeat } from "../api/types";
import { api } from "../api/client";
import { Karaoke } from "./Karaoke";

interface Props {
  beat: ProjectBeat;
  irBeat: IRBeat | null;
  /** Rendered draft mp4 path, if one exists. */
  previewPath: string | null;
}

export function ScriptTab({ beat, irBeat, previewPath }: Props) {
  const words = irBeat?.words ?? [];
  const audioPath = beat.audio || irBeat?.audio || "";
  const canKaraoke = !!audioPath && words.length > 0;

  return (
    <div class="tab-body">
      {previewPath && (
        <div class="preview">
          <video
            controls
            preload="metadata"
            src={api.fileUrl(previewPath) + "&t=" + Date.now()}
          />
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
