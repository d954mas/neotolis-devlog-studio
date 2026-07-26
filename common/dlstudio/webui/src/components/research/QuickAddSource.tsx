import { useState } from "preact/hooks";
import type {
  ResearchQuickAddKind,
  ResearchQuickAddResult,
} from "../../api/research";

interface QuickAddSourceProps {
  busy: boolean;
  collectorConfigured: boolean;
  onAdd: (
    kind: ResearchQuickAddKind,
    value: string,
  ) => Promise<ResearchQuickAddResult>;
}

const COPY = {
  author: {
    label: "Ссылка на автора",
    placeholder: "instagram.com/juliusspeak или @juliusspeak",
    button: "Добавить автора",
    busy: "Добавляем…",
    hint: "Добавим автора в проект. Его Reels можно обновлять общей синхронизацией.",
  },
  reel: {
    label: "Ссылка на Reel",
    placeholder: "instagram.com/reel/…",
    button: "Добавить Reel",
    busy: "Получаем данные…",
    hint: "Автор, описание, дата, обложка и метрики загрузятся автоматически · 1 кредит.",
  },
} as const;

export function QuickAddSource({ busy, collectorConfigured, onAdd }: QuickAddSourceProps) {
  const [kind, setKind] = useState<ResearchQuickAddKind>("author");
  const [value, setValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const copy = COPY[kind];
  const reelUnavailable = kind === "reel" && !collectorConfigured;

  function choose(nextKind: ResearchQuickAddKind) {
    setKind(nextKind);
    setMessage(null);
    setInlineError(null);
  }

  async function submit(event: Event) {
    event.preventDefault();
    const source = value.trim();
    if (!source || reelUnavailable) return;
    setMessage(null);
    setInlineError(null);
    try {
      const result = await onAdd(kind, source);
      if (result.kind === "author") {
        setMessage(
          result.created
            ? `@${result.author.username} добавлен. Теперь можно синхронизировать его Reels.`
            : `@${result.author.username} уже есть в этом проекте.`,
        );
      } else {
        setMessage(
          `Reel @${result.author.username} добавлен вместе с описанием и метриками.`,
        );
      }
      setValue("");
    } catch (caught) {
      setInlineError((caught as Error).message);
    }
  }

  return (
    <section class="research-quick-add" aria-labelledby="quick-add-title">
      <div class="research-quick-add-head">
        <div>
          <span class="eyebrow">Новый источник</span>
          <h3 id="quick-add-title">Добавить в исследование</h3>
        </div>
        <div class="research-source-kind" aria-label="Что добавить">
          <button
            type="button"
            aria-pressed={kind === "author"}
            class={kind === "author" ? "active" : ""}
            onClick={() => choose("author")}
          >
            Автор
          </button>
          <button
            type="button"
            aria-pressed={kind === "reel"}
            class={kind === "reel" ? "active" : ""}
            onClick={() => choose("reel")}
          >
            Reel
          </button>
        </div>
      </div>

      <form class="research-quick-add-form" onSubmit={submit}>
        <label class="field-label">
          {copy.label}
          <input
            type="text"
            inputMode="url"
            autoComplete="off"
            value={value}
            onInput={(event) => setValue(event.currentTarget.value)}
            placeholder={copy.placeholder}
            required
          />
        </label>
        <button class="btn primary" disabled={busy || reelUnavailable}>
          {busy ? copy.busy : copy.button}
        </button>
      </form>

      <p class={`research-quick-add-hint ${reelUnavailable ? "warning" : ""}`}>
        {reelUnavailable
          ? "Для добавления Reel нужен ключ ScrapeCreators. Автора можно добавить без него."
          : copy.hint}
      </p>
      {message && <p class="research-quick-add-result" role="status">{message}</p>}
      {inlineError && <p class="research-quick-add-error" role="alert">{inlineError}</p>}
    </section>
  );
}
