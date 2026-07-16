import { useEffect, useRef, useState } from "preact/hooks";
import type { WordSpan } from "../api/types";
import { api } from "../api/client";

interface Props {
  audioPath: string;
  words: WordSpan[];
}

/** Index of the last word that has started by time t (or -1). Words ordered.
 * Using "last started" keeps the highlight stable across the small gaps
 * between word spans instead of flickering back to nothing. */
function activeWordAt(words: WordSpan[], t: number): number {
  let found = -1;
  for (let i = 0; i < words.length; i++) {
    if (words[i].t0 <= t) found = i;
    else break;
  }
  return found;
}

export function Karaoke({ audioPath, words }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const rafRef = useRef(0);
  const [idx, setIdx] = useState(-1);

  useEffect(() => {
    setIdx(-1);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [audioPath, words]);

  const loop = () => {
    const a = audioRef.current;
    if (!a) return;
    const found = activeWordAt(words, a.currentTime);
    setIdx((prev) => (prev === found ? prev : found));
    rafRef.current = requestAnimationFrame(loop);
  };

  const start = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(loop);
  };
  const stop = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
  };

  const seekTo = (w: WordSpan) => {
    const a = audioRef.current;
    if (a) {
      a.currentTime = w.t0;
      setIdx(activeWordAt(words, w.t0));
    }
  };

  return (
    <div>
      <audio
        ref={audioRef}
        class="karaoke-audio"
        controls
        preload="metadata"
        src={api.fileUrl(audioPath)}
        onPlay={start}
        onPlaying={start}
        onPause={stop}
        onEnded={() => {
          stop();
          setIdx(-1);
        }}
        onSeeked={() => {
          const a = audioRef.current;
          if (a) setIdx(activeWordAt(words, a.currentTime));
        }}
      />
      <div class="vo-text karaoke">
        {words.map((w, i) => {
          const cls =
            i === idx ? "word active" : idx >= 0 && i < idx ? "word past" : "word upcoming";
          return (
            <span key={i} class={cls} onClick={() => seekTo(w)}>
              {w.text}
              {i < words.length - 1 ? " " : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}
