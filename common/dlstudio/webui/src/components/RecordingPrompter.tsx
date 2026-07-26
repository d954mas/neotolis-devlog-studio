interface Props {
  text: string;
  elapsed: number;
  recording: boolean;
  countdownSeconds?: number;
  roomToneSeconds?: number;
  postRolling?: boolean;
}

interface Page {
  start: number;
  end: number;
}

const WORDS_PER_SECOND = 1.55;
const MAX_WORDS_PER_PAGE = 11;
const MIN_PAGE_SECONDS = 2.6;
export const DEFAULT_COUNTDOWN_SECONDS = 3;
export const DEFAULT_ROOM_TONE_SECONDS = 2;

function wordsOf(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean);
}

function semanticPages(words: string[]): Page[] {
  const pages: Page[] = [];
  let start = 0;
  for (let i = 0; i < words.length; i++) {
    const count = i - start + 1;
    const strongBreak = /[.!?…]$/.test(words[i]);
    const softBreak = /[,;:]$/.test(words[i]);
    const atEnd = i === words.length - 1;
    if (
      atEnd ||
      (count >= 3 && strongBreak) ||
      (count >= 7 && softBreak) ||
      count >= MAX_WORDS_PER_PAGE
    ) {
      pages.push({ start, end: i + 1 });
      start = i + 1;
    }
  }
  return pages;
}

function positionAt(words: string[], pages: Page[], elapsed: number) {
  let cursor = 0;
  for (let i = 0; i < pages.length; i++) {
    const page = pages[i];
    const duration = Math.max(
      MIN_PAGE_SECONDS,
      (page.end - page.start) / WORDS_PER_SECOND,
    );
    if (elapsed < cursor + duration) {
      const word = Math.min(
        page.end - 1,
        page.start + Math.max(0, Math.floor((elapsed - cursor) * WORDS_PER_SECOND)),
      );
      return { page: i, word };
    }
    cursor += duration;
  }
  const lastPage = Math.max(0, pages.length - 1);
  return { page: lastPage, word: Math.max(0, words.length - 1) };
}

function wordClass(index: number, active: number): string {
  if (index < active) return "word past";
  if (index === active) return "word active";
  return "word upcoming";
}

export function RecordingPrompter({
  text,
  elapsed,
  recording,
  countdownSeconds = DEFAULT_COUNTDOWN_SECONDS,
  roomToneSeconds = DEFAULT_ROOM_TONE_SECONDS,
  postRolling = false,
}: Props) {
  const words = wordsOf(text);
  const pages = semanticPages(words);
  if (!words.length || !pages.length) return null;

  const countingDown = recording && elapsed < countdownSeconds;
  const roomTone = (
    recording
    && !countingDown
    && elapsed < countdownSeconds + roomToneSeconds
  );
  const waiting = countingDown || roomTone || postRolling;
  const readingElapsed = recording
    ? Math.max(0, elapsed - countdownSeconds - roomToneSeconds)
    : 0;
  const countdown = Math.max(1, Math.ceil(countdownSeconds - elapsed));
  const position = positionAt(words, pages, readingElapsed);
  const current = pages[position.page];
  const next = pages[position.page + 1];

  return (
    <div class={"recording-prompter" + (recording ? " recording" : "")}>
      <section class="prompter-head" aria-label="Recording teleprompter">
        <div class="prompter-label">
          {postRolling
            ? "Recording · post-roll"
            : countingDown
              ? "Recording · countdown"
              : roomTone
                ? "Recording · room tone"
                : recording
                  ? "Read now"
                  : "Ready"}
        </div>
        <div
          class={"prompter-current" + (waiting ? " countdown" : "")}
          aria-live="polite"
          aria-atomic="true"
        >
          {postRolling ? (
            <span class="countdown-number">1</span>
          ) : countingDown ? (
            <span class="countdown-number">{countdown}</span>
          ) : roomTone ? (
            <span class="countdown-number">Тишина</span>
          ) : (
            words.slice(current.start, current.end).map((word, offset) => {
              const index = current.start + offset;
              return (
                <span key={index} class={wordClass(index, position.word)}>
                  {word}{offset < current.end - current.start - 1 ? " " : ""}
                </span>
              );
            })
          )}
        </div>
        <div class="prompter-next">
          {postRolling
            ? "Не нажимайте ничего · сохраняю чистый хвост"
            : countingDown
              ? "Запись уже идёт · приготовьтесь"
              : roomTone
                ? "Ещё 2 секунды тишины · затем начинайте"
            : next
              ? `Next: ${words.slice(next.start, next.end).join(" ")}`
              : "Last phrase"}
        </div>
      </section>

      <div class="prompter-full" aria-label="Full script">
        {words.map((word, index) => (
          <span
            key={index}
            class={waiting ? "word upcoming" : wordClass(index, position.word)}
          >
            {word}{index < words.length - 1 ? " " : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
