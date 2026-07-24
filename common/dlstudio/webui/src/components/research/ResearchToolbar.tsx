import type { ComponentChildren } from "preact";
import type {
  ResearchProjectFeed,
  ResearchProjectSummary,
  ResearchSort,
  ResearchWindow,
} from "../../api/research";

export type ResearchPanel = "add" | "tools" | null;

interface Props {
  projects: ResearchProjectSummary[];
  activeId: string | null;
  feed: ResearchProjectFeed | null;
  range: ResearchWindow;
  sort: ResearchSort;
  busy: boolean;
  collectorConfigured: boolean;
  syncLabel: string;
  syncDisabled: boolean;
  panel: ResearchPanel;
  addPanel: ComponentChildren;
  toolsPanel: ComponentChildren;
  onProject: (projectId: string) => void;
  onRange: (range: ResearchWindow) => void;
  onSort: (sort: ResearchSort) => void;
  onSync: () => void;
  onPanel: (panel: ResearchPanel) => void;
}

const WINDOWS: Array<[ResearchWindow, string]> = [
  ["7d", "7д"],
  ["30d", "30д"],
  ["90d", "90д"],
  ["all", "Всё"],
];

export function ResearchToolbar({
  projects,
  activeId,
  feed,
  range,
  sort,
  busy,
  collectorConfigured,
  syncLabel,
  syncDisabled,
  panel,
  addPanel,
  toolsPanel,
  onProject,
  onRange,
  onSort,
  onSync,
  onPanel,
}: Props) {
  return (
    <div class="research-command-shell">
      <header class="research-commandbar">
        <a href="/" class="research-command-brand" aria-label="Открыть Video Studio">
          <span aria-hidden="true">←</span> Studio
        </a>
        <h1>Pattern Lab</h1>

        <label class="research-project-select">
          <span class="sr-only">Проект исследования</span>
          <select
            value={activeId || ""}
            disabled={projects.length === 0}
            onChange={(event) => onProject(event.currentTarget.value)}
          >
            {projects.length === 0 && <option value="">Нет проектов</option>}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.title}</option>
            ))}
          </select>
        </label>

        <button
          class={`btn sm ${panel === "add" ? "primary" : "secondary"}`}
          disabled={!feed}
          aria-expanded={panel === "add"}
          onClick={() => onPanel(panel === "add" ? null : "add")}
        >
          + Добавить
        </button>

        <button
          class="btn sm secondary research-sync-button"
          disabled={busy || syncDisabled}
          title={collectorConfigured ? "Обновить Reels" : "Настройте сборщик в меню инструментов"}
          onClick={onSync}
        >
          <span class={`research-sync-dot ${collectorConfigured ? "ready" : "offline"}`} aria-hidden="true" />
          {busy ? "Обновляю…" : syncLabel}
        </button>

        <div class="research-command-spacer" />

        {feed && (
          <>
            <div class="research-window" aria-label="Период публикации">
              {WINDOWS.map(([id, label]) => (
                <button
                  key={id}
                  aria-pressed={range === id}
                  class={range === id ? "active" : ""}
                  onClick={() => onRange(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label class="research-sort compact">
              <span class="sr-only">Режим ленты</span>
              <select value={sort} onChange={(event) => onSort(event.currentTarget.value as ResearchSort)}>
                <option value="newest">История · новые сверху</option>
                <option value="outlier">Рекомендации</option>
                <option value="views">По просмотрам</option>
                <option value="velocity">Сейчас растут</option>
              </select>
            </label>
          </>
        )}

        <button
          class={`research-tools-button ${panel === "tools" ? "active" : ""}`}
          aria-label="Инструменты и настройки"
          aria-expanded={panel === "tools"}
          onClick={() => onPanel(panel === "tools" ? null : "tools")}
        >
          •••
        </button>
      </header>

      {panel === "add" && (
        <section class="research-command-panel add" aria-label="Добавить источник">
          {addPanel}
        </section>
      )}
      {panel === "tools" && (
        <section class="research-command-panel tools" aria-label="Инструменты и настройки">
          {toolsPanel}
        </section>
      )}
    </div>
  );
}
