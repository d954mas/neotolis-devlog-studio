import { useEffect, useState } from "preact/hooks";
import {
  researchApi,
  type ExperimentInput,
  type ExperimentResultInput,
  type ResearchCollectorStatus,
  type ResearchMediaCacheSummary,
  type ResearchProjectFeed,
  type ResearchProjectSummary,
  type ResearchQuickAddKind,
  type ResearchQuickAddResult,
  type ResearchReel,
  type ResearchSort,
  type ResearchWindow,
  type ResearchSyncResult,
  type ReelInput,
} from "../../api/research";
import { ReelCard } from "./ReelCard";
import { AuthorForm, ProjectForm, ReferenceForm } from "./ResearchForms";
import { QuickAddSource } from "./QuickAddSource";
import { ReelDateHeader } from "./ReelDateHeader";
import { ResearchToolbar, type ResearchPanel } from "./ResearchToolbar";
import { dateGroupLabel, groupReelsByDate } from "./research-feed-dates";

function queryValue(name: string): string | null {
  return typeof location === "undefined" ? null : new URLSearchParams(location.search).get(name);
}

function initialWindow(): ResearchWindow {
  const value = queryValue("range");
  return value === "7d" || value === "30d" || value === "90d" ? value : "all";
}

function initialSort(): ResearchSort {
  const value = queryValue("sort");
  return value === "velocity" || value === "views" || value === "outlier" ? value : "newest";
}

export function ResearchLab() {
  const [projects, setProjects] = useState<ResearchProjectSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(() => queryValue("project"));
  const [feed, setFeed] = useState<ResearchProjectFeed | null>(null);
  const [range, setRange] = useState<ResearchWindow>(initialWindow);
  const [sort, setSort] = useState<ResearchSort>(initialSort);
  const [authorId, setAuthorId] = useState<string | null>(() => queryValue("author"));
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collector, setCollector] = useState<ResearchCollectorStatus | null>(null);
  const [syncResult, setSyncResult] = useState<ResearchSyncResult | null>(null);
  const [mediaCache, setMediaCache] = useState<ResearchMediaCacheSummary | null>(null);
  const [panel, setPanel] = useState<ResearchPanel>(null);

  async function refreshMediaCache() {
    setMediaCache(await researchApi.mediaCache());
  }

  async function loadProjects(preferred?: string) {
    const items = await researchApi.projects();
    setProjects(items);
    setActiveId((current) => {
      const requested = preferred || current;
      return items.some((item) => item.id === requested) ? requested : items[0]?.id || null;
    });
  }

  async function loadFeed(projectId = activeId, cursor: string | null = null) {
    if (!projectId) {
      setFeed(null);
      setLoading(false);
      return;
    }
    if (cursor) setLoadingMore(true);
    else setLoading(true);
    try {
      const page = await researchApi.project(projectId, range, sort, authorId, cursor);
      setFeed((current) => {
        if (!cursor || !current || current.id !== page.id) return page;
        const reelIds = new Set(current.reels.map((reel) => reel.id));
        const experimentIds = new Set(current.experiments.map((experiment) => experiment.id));
        return {
          ...page,
          reels: [...current.reels, ...page.reels.filter((reel) => !reelIds.has(reel.id))],
          experiments: [
            ...current.experiments,
            ...page.experiments.filter((experiment) => !experimentIds.has(experiment.id)),
          ],
        };
      });
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      if (cursor) setLoadingMore(false);
      else setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects().catch((caught) => {
      setError((caught as Error).message);
      setLoading(false);
    });
    researchApi.collectorStatus().then(setCollector).catch((caught) => {
      setError((caught as Error).message);
    });
    refreshMediaCache().catch((caught) => setError((caught as Error).message));
  }, []);

  useEffect(() => {
    loadFeed();
  }, [activeId, range, sort, authorId]);

  useEffect(() => {
    if (!panel) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPanel(null);
    };
    addEventListener("keydown", closeOnEscape);
    return () => removeEventListener("keydown", closeOnEscape);
  }, [panel]);

  useEffect(() => {
    if (typeof location === "undefined" || !location.pathname.startsWith("/research")) return;
    const url = new URL(location.href);
    if (activeId) url.searchParams.set("project", activeId);
    else url.searchParams.delete("project");
    url.searchParams.set("range", range);
    url.searchParams.set("sort", sort);
    if (authorId) url.searchParams.set("author", authorId);
    else url.searchParams.delete("author");
    history.replaceState(null, "", url);
  }, [activeId, range, sort, authorId]);

  async function mutate(action: () => Promise<unknown>, refreshProjects = false): Promise<boolean> {
    setBusy(true);
    try {
      await action();
      if (refreshProjects) await loadProjects(activeId || undefined);
      await loadFeed();
      setError(null);
      return true;
    } catch (caught) {
      setError((caught as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const selectedAuthor = feed?.authors.find((author) => author.id === authorId) || null;
  const syncAuthorCount = selectedAuthor ? 1 : (feed?.authors.length || 0);
  const syncMaxCredits = syncAuthorCount * (collector?.max_credits_per_author || 2);

  async function syncAuthors() {
    if (!feed) return;
    setBusy(true);
    setSyncResult(null);
    try {
      const result = await researchApi.syncProject(
        feed.id,
        selectedAuthor ? [selectedAuthor.id] : undefined,
      );
      setSyncResult(result);
      await loadProjects(feed.id);
      await loadFeed(feed.id);
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function quickAddSource(
    kind: ResearchQuickAddKind,
    value: string,
  ): Promise<ResearchQuickAddResult> {
    if (!feed) throw new Error("Сначала выберите проект");
    setBusy(true);
    try {
      const result = await researchApi.quickAdd(feed.id, kind, value);
      await loadProjects(feed.id);
      await loadFeed(feed.id);
      setError(null);
      return result;
    } catch (caught) {
      setError((caught as Error).message);
      throw caught;
    } finally {
      setBusy(false);
    }
  }

  async function createResearchProject(input: { title: string; description: string; style_profile: string }): Promise<boolean> {
    setBusy(true);
    try {
      const created = await researchApi.createProject(input);
      await loadProjects(created.id);
      setPanel(null);
      setError(null);
      return true;
    } catch (caught) {
      setError((caught as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function clearMediaCache() {
    if (!confirm("Удалить все скачанные видео? Авторы, метрики, заметки и эксперименты останутся.")) return;
    setBusy(true);
    try {
      await researchApi.clearMediaCache();
      await refreshMediaCache();
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function renderReelCard(reel: ResearchReel, showDate: boolean) {
    if (!feed) return null;
    return (
      <ReelCard
        key={reel.id}
        projectId={feed.id}
        reel={reel}
        showDate={showDate}
        experimentBusy={busy}
        onAuthor={setAuthorId}
        onExperiment={(input: ExperimentInput) => mutate(() => researchApi.createExperiment(feed.id, input), true)}
        onExperimentResult={(experimentId: string, input: ExperimentResultInput) => mutate(() => researchApi.recordExperimentResult(feed.id, experimentId, input), true)}
        onCacheChange={() => { refreshMediaCache().catch((caught) => setError((caught as Error).message)); }}
      />
    );
  }

  return (
    <section class="research-lab" aria-label="Research projects and Reel feed">
      <ResearchToolbar
        projects={projects}
        activeId={activeId}
        feed={feed}
        range={range}
        sort={sort}
        busy={busy}
        collectorConfigured={Boolean(collector?.configured)}
        syncLabel={selectedAuthor ? `Sync @${selectedAuthor.username}` : "Sync"}
        syncDisabled={!collector?.configured || syncAuthorCount === 0 || syncAuthorCount > (collector?.max_authors_per_sync || 25)}
        panel={panel}
        onProject={(projectId) => {
          setPanel(null);
          setAuthorId(null);
          setActiveId(projectId);
        }}
        onRange={setRange}
        onSort={setSort}
        onSync={syncAuthors}
        onPanel={setPanel}
        addPanel={feed ? (
          <QuickAddSource
            busy={busy}
            collectorConfigured={Boolean(collector?.configured)}
            onAdd={quickAddSource}
          />
        ) : null}
        toolsPanel={(
          <div class="research-tools-panel">
            <header class="research-tools-head">
              <div><span class="eyebrow">Workspace</span><h2>Инструменты</h2></div>
              <button class="research-panel-close" aria-label="Закрыть" onClick={() => setPanel(null)}>×</button>
            </header>

            {feed && (
              <section class="research-project-context">
                <div>
                  <span class="eyebrow">Текущий проект</span>
                  <h3>{feed.title}</h3>
                  <p>{feed.description || "Цель исследования пока не описана."}</p>
                </div>
                <small>{feed.counts.authors} авторов · {feed.counts.reels} Reels · {feed.counts.experiments} экспериментов</small>
                <code title="Стабильный контекст для агентов">{feed.agent_brief_path}</code>
                {feed.style_profile && <p class="research-project-style"><b>Наш стиль:</b> {feed.style_profile}</p>}
              </section>
            )}

            {feed && (
              <section class={`research-collector ${collector?.configured ? "connected" : "needs-key"}`} aria-label="Сборщик Reels">
                <div class="research-collector-copy">
                  <span class="eyebrow">Сборщик</span>
                  <h3>ScrapeCreators</h3>
                  {collector?.configured ? (
                    <p>Подключён. Обновляет публичные Reels, сохраняя заметки.</p>
                  ) : (
                    <p>Для синхронизации задайте <code>SCRAPECREATORS_API_KEY</code> перед запуском Studio.</p>
                  )}
                </div>
                <div class="research-collector-action">
                  <span class={`research-provider-status ${collector?.configured ? "ready" : "offline"}`}>
                    {collector?.configured ? "Подключён" : "Нужен ключ"}
                  </span>
                  <button class="btn sm primary" disabled={busy || !collector?.configured || syncAuthorCount === 0} onClick={syncAuthors}>
                    {busy ? "Обновляю…" : selectedAuthor ? `Обновить @${selectedAuthor.username}` : "Обновить авторов"}
                  </button>
                  <small>До {syncMaxCredits} запросов за запуск</small>
                </div>
                {syncResult && <p class="research-sync-result" role="status">Импортировано {syncResult.reels_imported} Reels · {syncResult.credits_used} запросов.</p>}
              </section>
            )}

            <section class="research-media-cache" aria-label="Локальный видеокэш">
              <div>
                <span class="eyebrow">Локально</span>
                <b>Видеокэш</b>
                <small>{mediaCache?.file_count || 0} видео · {mediaCache ? `${(mediaCache.size_bytes / (1024 * 1024)).toFixed(1)} MB` : "считаю…"}</small>
              </div>
              <button class="btn sm secondary" disabled={busy || !mediaCache?.file_count} onClick={clearMediaCache}>Очистить</button>
            </section>

            {feed && (
              <details class="research-setup research-advanced-import">
                <summary>Расширенный ручной импорт</summary>
                <div class="research-setup-grid">
                  <div><h3>Добавить автора</h3><AuthorForm busy={busy} onCreate={(input) => mutate(() => researchApi.addAuthor(feed.id, input), true)} /></div>
                  <div><h3>Импортировать Reel</h3>{feed.authors.length ? <ReferenceForm authors={feed.authors} busy={busy} onCreate={(input: ReelInput) => mutate(() => researchApi.addReel(feed.id, input), true)} /> : <p class="hint">Сначала добавьте автора.</p>}</div>
                </div>
              </details>
            )}

            <details class="research-setup research-new-project" open={projects.length === 0}>
              <summary>Новый проект исследования</summary>
              <ProjectForm busy={busy} onCreate={createResearchProject} />
            </details>
          </div>
        )}
      />
      <div class="research-feed-pane">
        {error && <div class="research-error" role="alert">{error}</div>}
        {!activeId ? (
          <div class="research-empty"><span aria-hidden="true">◇</span><h3>Create a research project</h3><p>Group creators and references around one learning goal.</p></div>
        ) : loading && !feed ? (
          <div class="research-loading" aria-busy="true">Loading research feed…</div>
        ) : feed ? (
          <>
            {selectedAuthor && (
              <section class="author-focus" aria-label={`Filtered by @${selectedAuthor.username}`}>
                <div><span class="eyebrow">Author focus</span><h3>@{selectedAuthor.username}</h3></div>
                <span><b>{selectedAuthor.followers_count?.toLocaleString() || "—"}</b> followers</span>
                <span><b>{selectedAuthor.median_views?.toLocaleString() || "—"}</b> typical views</span>
                <button class="btn sm secondary" onClick={() => setAuthorId(null)}>Show all authors</button>
              </section>
            )}

            <div class="research-feed" aria-live="polite">
              {loading && <div class="research-refreshing">Refreshing…</div>}
              {!loading && feed.reels.length === 0 ? (
                <div class="research-empty"><span aria-hidden="true">▶</span><h3>No Reels in this window</h3><p>Import a reference above or choose a wider period.</p></div>
              ) : sort === "newest" ? (
                groupReelsByDate(feed.reels).map((group) => (
                  <section class="research-date-group" key={group.date} aria-label={dateGroupLabel(group.publishedAt)}>
                    <ReelDateHeader publishedAt={group.publishedAt} count={group.reels.length} />
                    <div class="research-feed-grid">
                      {group.reels.map((reel) => renderReelCard(reel, false))}
                    </div>
                  </section>
                ))
              ) : (
                <div class="research-feed-grid research-ranked-grid">
                  {feed.reels.map((reel) => renderReelCard(reel, true))}
                </div>
              )}
              {feed.page.has_more && (
                <div class="research-load-more">
                  <button
                    class="btn secondary"
                    disabled={loadingMore || !feed.page.next_cursor}
                    onClick={() => loadFeed(feed.id, feed.page.next_cursor)}
                  >
                    {loadingMore ? "Загружаю…" : `Показать ещё · ${feed.reels.length} из ${feed.page.total}`}
                  </button>
                </div>
              )}
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}
