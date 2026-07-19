import { useEffect, useState } from "preact/hooks";
import {
  researchApi,
  type ExperimentInput,
  type ExperimentResultInput,
  type ResearchCollectorStatus,
  type ResearchProjectFeed,
  type ResearchProjectSummary,
  type ResearchSort,
  type ResearchWindow,
  type ResearchSyncResult,
  type ReelInput,
} from "../../api/research";
import { ReelCard } from "./ReelCard";
import { AuthorForm, ProjectForm, ReferenceForm } from "./ResearchForms";

const WINDOWS: Array<[ResearchWindow, string]> = [["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"], ["all", "All time"]];

function queryValue(name: string): string | null {
  return typeof location === "undefined" ? null : new URLSearchParams(location.search).get(name);
}

function initialWindow(): ResearchWindow {
  const value = queryValue("range");
  return value === "30d" || value === "90d" || value === "all" ? value : "7d";
}

function initialSort(): ResearchSort {
  const value = queryValue("sort");
  return value === "velocity" || value === "views" || value === "newest" ? value : "outlier";
}

export function ResearchLab() {
  const [projects, setProjects] = useState<ResearchProjectSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(() => queryValue("project"));
  const [feed, setFeed] = useState<ResearchProjectFeed | null>(null);
  const [range, setRange] = useState<ResearchWindow>(initialWindow);
  const [sort, setSort] = useState<ResearchSort>(initialSort);
  const [authorId, setAuthorId] = useState<string | null>(() => queryValue("author"));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collector, setCollector] = useState<ResearchCollectorStatus | null>(null);
  const [syncResult, setSyncResult] = useState<ResearchSyncResult | null>(null);

  async function loadProjects(preferred?: string) {
    const items = await researchApi.projects();
    setProjects(items);
    setActiveId((current) => {
      const requested = preferred || current;
      return items.some((item) => item.id === requested) ? requested : items[0]?.id || null;
    });
  }

  async function loadFeed(projectId = activeId) {
    if (!projectId) {
      setFeed(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setFeed(await researchApi.project(projectId, range, sort, authorId));
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setLoading(false);
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
  }, []);

  useEffect(() => {
    loadFeed();
  }, [activeId, range, sort, authorId]);

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

  return (
    <section class="research-lab" aria-label="Research projects and Reel feed">
      <aside class="research-projects">
        <div class="research-brand"><span class="eyebrow">Library</span><h2>Projects</h2></div>
        <nav aria-label="Research projects">
          {projects.map((project) => (
            <button
              key={project.id}
              class={`research-project-item ${activeId === project.id ? "active" : ""}`}
              onClick={() => { setAuthorId(null); setActiveId(project.id); }}
              aria-current={activeId === project.id ? "page" : undefined}
            >
              <b>{project.title}</b>
              <span>{project.author_count} authors · {project.reel_count} Reels</span>
              <small>{project.experiment_count} experiments</small>
            </button>
          ))}
        </nav>
        <details class="research-add-project" open={projects.length === 0}>
          <summary>New research project</summary>
          <ProjectForm busy={busy} onCreate={async (input) => {
            setBusy(true);
            try {
              const created = await researchApi.createProject(input);
              await loadProjects(created.id);
              setError(null);
              return true;
            } catch (caught) {
              setError((caught as Error).message);
              return false;
            } finally {
              setBusy(false);
            }
          }} />
        </details>
      </aside>

      <div class="research-feed-pane">
        {error && <div class="research-error" role="alert">{error}</div>}
        {!activeId ? (
          <div class="research-empty"><span aria-hidden="true">◇</span><h3>Create a research project</h3><p>Group creators and references around one learning goal.</p></div>
        ) : loading && !feed ? (
          <div class="research-loading" aria-busy="true">Loading research feed…</div>
        ) : feed ? (
          <>
            <header class="research-feed-head">
              <div><span class="eyebrow">Research project</span><h2>{feed.title}</h2><p>{feed.description || "No research goal written yet."}</p><small class="research-project-stats">{feed.authors.length} authors · {feed.reels.length} references · {feed.experiments.length} experiments</small><code class="research-agent-brief" title="Stable project context for agents">Agent brief · {feed.agent_brief_path}</code></div>
              <div class="research-window" aria-label="Publication window">
                {WINDOWS.map(([id, label]) => <button key={id} aria-pressed={range === id} class={range === id ? "active" : ""} onClick={() => setRange(id)}>{label}</button>)}
              </div>
              <label class="research-sort">Sort<select value={sort} onChange={(event) => setSort(event.currentTarget.value as ResearchSort)}><option value="outlier">Outlier score</option><option value="velocity">Views per hour</option><option value="views">Views</option><option value="newest">Newest</option></select></label>
            </header>

            {feed.style_profile && (
              <section class="research-style-contract" aria-label="Original style contract">
                <span class="eyebrow">Keep every experiment recognisably ours</span>
                <p>{feed.style_profile}</p>
              </section>
            )}

            <section class={`research-collector ${collector?.configured ? "connected" : "needs-key"}`} aria-label="Automatic Reel collection">
              <div class="research-collector-copy">
                <span class="eyebrow">Automatic collection</span>
                <h3>ScrapeCreators</h3>
                {collector?.configured ? (
                  <p>Ready. One current Reels page per author; existing analysis notes stay intact.</p>
                ) : (
                  <p>Set <code>SCRAPECREATORS_API_KEY</code> before starting Studio to enable sync.</p>
                )}
              </div>
              <div class="research-collector-action">
                <span class={`research-provider-status ${collector?.configured ? "ready" : "offline"}`}>
                  {collector?.configured ? "Connected" : "Key needed"}
                </span>
                <button
                  class="btn sm primary"
                  disabled={busy || !collector?.configured || syncAuthorCount === 0 || syncAuthorCount > (collector?.max_authors_per_sync || 25)}
                  onClick={syncAuthors}
                >
                  {busy ? "Syncing…" : selectedAuthor ? `Sync @${selectedAuthor.username}` : `Sync ${syncAuthorCount || "all"} authors`}
                </button>
                <small>
                  Maximum {syncMaxCredits} credit{syncMaxCredits === 1 ? "" : "s"} this run
                  {collector ? ` · fallback included · under $${collector.max_paid_cost_per_sync_usd.toFixed(2)} at the paid rate` : ""}
                </small>
              </div>
              {syncAuthorCount > (collector?.max_authors_per_sync || 25) && (
                <p class="research-collector-warning">Select one author first; a run is capped at {collector?.max_authors_per_sync || 25} credits.</p>
              )}
              {syncResult && (
                <p class="research-sync-result" role="status">
                  Imported <b>{syncResult.reels_imported}</b> Reels from {syncResult.authors_completed} author{syncResult.authors_completed === 1 ? "" : "s"} using {syncResult.credits_used} credit{syncResult.credits_used === 1 ? "" : "s"}.
                  {syncResult.credits_remaining !== null ? ` ${syncResult.credits_remaining} credits remain.` : ""}
                </p>
              )}
            </section>

            {selectedAuthor && (
              <section class="author-focus" aria-label={`Filtered by @${selectedAuthor.username}`}>
                <div><span class="eyebrow">Author focus</span><h3>@{selectedAuthor.username}</h3></div>
                <span><b>{selectedAuthor.followers_count?.toLocaleString() || "—"}</b> followers</span>
                <span><b>{selectedAuthor.median_views?.toLocaleString() || "—"}</b> typical views</span>
                <button class="btn sm secondary" onClick={() => setAuthorId(null)}>Show all authors</button>
              </section>
            )}

            <details class="research-setup" open={feed.authors.length === 0}>
              <summary>Manage sources</summary>
              <div class="research-setup-grid">
                <div><h3>Add author</h3><AuthorForm busy={busy} onCreate={(input) => mutate(() => researchApi.addAuthor(feed.id, input), true)} /></div>
                <div><h3>Import or update a reference</h3>{feed.authors.length ? <><p class="hint">Submitting the same Reel URL again adds a fresh metric snapshot without losing your hook and pattern notes.</p><ReferenceForm authors={feed.authors} busy={busy} onCreate={(input: ReelInput) => mutate(() => researchApi.addReel(feed.id, input), true)} /></> : <p class="hint">Add an author first. Automatic collection will plug into this same import contract.</p>}</div>
              </div>
            </details>

            <div class="research-feed" aria-live="polite">
              {loading && <div class="research-refreshing">Refreshing…</div>}
              {!loading && feed.reels.length === 0 ? (
                <div class="research-empty"><span aria-hidden="true">▶</span><h3>No Reels in this window</h3><p>Import a reference above or choose a wider period.</p></div>
              ) : feed.reels.map((reel) => (
                <ReelCard
                  key={reel.id}
                  reel={reel}
                  experimentBusy={busy}
                  onAuthor={setAuthorId}
                  onExperiment={(input: ExperimentInput) => mutate(() => researchApi.createExperiment(feed.id, input), true)}
                  onExperimentResult={(experimentId: string, input: ExperimentResultInput) => mutate(() => researchApi.recordExperimentResult(feed.id, experimentId, input), true)}
                />
              ))}
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}
