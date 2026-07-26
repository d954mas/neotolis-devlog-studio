import { useState } from "preact/hooks";
import { researchApi, type ResearchMediaStatus, type ResearchReel } from "../../api/research";

interface Props {
  projectId: string;
  reel: ResearchReel;
  onCacheChange: () => void;
}

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

export function ReelMedia({ projectId, reel, onCacheChange }: Props) {
  const [media, setMedia] = useState<ResearchMediaStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function openCachedVideo() {
    setBusy(true);
    try {
      const result = await researchApi.cacheReelMedia(projectId, reel.id);
      setMedia(result);
      setError(null);
      onCacheChange();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function removeCachedVideo() {
    setBusy(true);
    try {
      await researchApi.deleteReelMedia(projectId, reel.id);
      setMedia(null);
      setError(null);
      onCacheChange();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (media?.cached && media.media_url) {
    return (
      <section class="reel-media" aria-label={`Cached Reel by @${reel.author.username}`}>
        <video
          controls
          playsInline
          preload="metadata"
          poster={reel.thumbnail_url || undefined}
          src={media.media_url}
        />
        <div class="reel-media-foot">
          <span>Локальный кэш · {formatBytes(media.size_bytes)}</span>
          <button class="btn sm secondary" disabled={busy} onClick={removeCachedVideo}>
            {busy ? "Удаляю…" : "Удалить видео"}
          </button>
        </div>
      </section>
    );
  }

  return (
    <div class="reel-media-trigger">
      <button class="btn sm primary" disabled={busy} onClick={openCachedVideo}>
        {busy ? "Скачиваю…" : "Скачать и смотреть"}
      </button>
      {error && <span class="reel-media-error" role="alert">{error}</span>}
    </div>
  );
}
