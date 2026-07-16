import { useEffect, useRef, useState } from "preact/hooks";
import { api, pollJob } from "./api/client";
import type {
  CheckReport,
  Feedback,
  Project,
  Timeline,
} from "./api/types";
import type { SessionTake } from "./lib/takes";
import { CheckBanner } from "./components/CheckBanner";
import { Sidebar } from "./components/Sidebar";
import { ScriptTab } from "./components/ScriptTab";
import { RecordTab } from "./components/RecordTab";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { IRInspector } from "./components/IRInspector";

type Tab = "script" | "record" | "feedback" | "ir";
type RenderState = "idle" | "running" | "done" | "error";

interface RenderInfo {
  state: RenderState;
  msg: string;
}

function resultPath(result: unknown): string | null {
  if (typeof result === "string") return result;
  if (result && typeof result === "object") {
    const o = result as Record<string, unknown>;
    for (const k of ["path", "output", "mp4", "file", "preview"]) {
      if (typeof o[k] === "string") return o[k] as string;
    }
  }
  return null;
}

export function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [projectErr, setProjectErr] = useState<string | null>(null);
  const [ir, setIr] = useState<Timeline | null>(null);
  const [irErr, setIrErr] = useState<string | null>(null);
  const [check, setCheck] = useState<CheckReport | null>(null);
  const [checkErr, setCheckErr] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback>({});

  const [activeBeatId, setActiveBeatId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("script");

  const [takesByBeat, setTakesByBeat] = useState<Record<string, SessionTake[]>>(
    {},
  );
  const [renderInfo, setRenderInfo] = useState<Record<string, RenderInfo>>({});
  const [renderPreview, setRenderPreview] = useState<Record<string, string>>(
    {},
  );
  // Cache-buster token, set ONCE per completed render job (not per render
  // pass) so the preview <video> src is stable across re-renders and only
  // reloads when a fresh render actually lands. (L4)
  const [renderToken, setRenderToken] = useState<Record<string, number>>({});

  // In-flight render job pollers, aborted on unmount so pollJob loops don't
  // leak past the component's life. (L2)
  const renderAborters = useRef<Set<AbortController>>(new Set());
  useEffect(
    () => () => {
      renderAborters.current.forEach((a) => a.abort());
      renderAborters.current.clear();
    },
    [],
  );

  // Revoke recorded-take object URLs on unmount so their blobs are freed. (L3)
  const takesRef = useRef(takesByBeat);
  takesRef.current = takesByBeat;
  useEffect(
    () => () => {
      for (const list of Object.values(takesRef.current)) {
        for (const t of list) if (t.url) URL.revokeObjectURL(t.url);
      }
    },
    [],
  );

  // ── loaders ──────────────────────────────────────────────────────────────
  async function loadProject() {
    try {
      setProject(await api.project());
      setProjectErr(null);
    } catch (e) {
      setProjectErr((e as Error).message);
    }
  }
  async function loadIR() {
    try {
      setIr(await api.ir());
      setIrErr(null);
    } catch (e) {
      setIrErr((e as Error).message);
    }
  }
  async function loadCheck() {
    try {
      setCheck(await api.check());
      setCheckErr(null);
    } catch (e) {
      setCheckErr((e as Error).message);
    }
  }
  async function loadFeedback() {
    try {
      setFeedback(await api.feedback());
    } catch {
      /* feedback may not exist yet; keep quiet */
    }
  }

  useEffect(() => {
    loadProject();
    loadIR();
    loadCheck();
    loadFeedback();
  }, []);

  // Select first beat once the project arrives.
  useEffect(() => {
    if (project && !activeBeatId && project.beats.length) {
      setActiveBeatId(project.beats[0].id);
    }
  }, [project]);

  // Agents write feedback asynchronously — poll gently.
  useEffect(() => {
    const id = window.setInterval(loadFeedback, 7000);
    return () => clearInterval(id);
  }, []);

  // ── take state ─────────────────────────────────────────────────────────
  function addTake(t: SessionTake) {
    setTakesByBeat((m) => ({ ...m, [t.beatId]: [...(m[t.beatId] || []), t] }));
  }
  function updateTake(id: string, patch: Partial<SessionTake>) {
    setTakesByBeat((m) => {
      const out: Record<string, SessionTake[]> = {};
      for (const bid of Object.keys(m)) {
        out[bid] = m[bid].map((t) => (t.id === id ? { ...t, ...patch } : t));
      }
      return out;
    });
  }
  function afterProcess() {
    loadProject();
    loadIR();
    loadCheck();
    loadFeedback();
  }

  // ── render action ────────────────────────────────────────────────────────
  async function renderBeat(beatId: string) {
    // Named profile, resolved server-side through the ONE orientation-aware
    // table the CLI uses (defect 0.6) — the webui never computes pixels.
    const width = "540p";
    const ctrl = new AbortController();
    renderAborters.current.add(ctrl);
    setRenderInfo((s) => ({
      ...s,
      [beatId]: { state: "running", msg: "rendering…" },
    }));
    try {
      const { job_id } = await api.renderBeat({
        beat_id: beatId,
        width,
        quality: "draft",
      });
      const final = await pollJob(job_id, {
        signal: ctrl.signal,
        onStatus: (st) =>
          setRenderInfo((s) => ({
            ...s,
            [beatId]: { state: "running", msg: st.status },
          })),
      });
      if (final.status === "done") {
        const p = resultPath(final.result) ?? `data/finalize/${beatId}.mp4`;
        setRenderPreview((s) => ({ ...s, [beatId]: p }));
        // one fresh cache-buster per completed render (L4)
        setRenderToken((s) => ({ ...s, [beatId]: Date.now() }));
        setRenderInfo((s) => ({
          ...s,
          [beatId]: { state: "done", msg: "done" },
        }));
        loadProject();
        loadCheck();
        loadIR();
      } else {
        setRenderInfo((s) => ({
          ...s,
          [beatId]: { state: "error", msg: final.error || "render failed" },
        }));
      }
    } catch (e) {
      if (ctrl.signal.aborted) return; // unmounted mid-poll — drop silently
      setRenderInfo((s) => ({
        ...s,
        [beatId]: { state: "error", msg: (e as Error).message },
      }));
    } finally {
      renderAborters.current.delete(ctrl);
    }
  }

  // ── render ─────────────────────────────────────────────────────────────
  const apiOk = !projectErr && project != null;
  const beat = project?.beats.find((b) => b.id === activeBeatId) || null;
  const irBeat = ir?.beats.find((b) => b.id === activeBeatId) || null;
  const beatTakes = activeBeatId ? takesByBeat[activeBeatId] || [] : [];
  const rInfo = activeBeatId ? renderInfo[activeBeatId] : undefined;
  const previewPath =
    beat && activeBeatId
      ? (renderPreview[activeBeatId] ??
        (beat.rendered ? `data/finalize/${beat.id}.mp4` : null))
      : null;
  const previewToken = activeBeatId ? renderToken[activeBeatId] : undefined;

  const design = project?.design;
  const designStr = design
    ? `${design.resolution[0]}×${design.resolution[1]} @ ${design.fps}fps`
    : "";

  const TABS: Array<[Tab, string]> = [
    ["script", "Script"],
    ["record", "Record"],
    ["feedback", "Feedback"],
    ["ir", "IR Inspector"],
  ];

  return (
    <>
      <header class="top">
        <h1>
          <span class="dot">●</span> Studio v2
          {project ? ` · ${project.edit_name}` : ""}
        </h1>
        {project && (
          <>
            <span class="stat">
              <b>{project.beats.length}</b> beats
            </span>
            <span class="stat">{designStr}</span>
          </>
        )}
        <div class="tabs" style={{ marginLeft: "12px" }}>
          {TABS.map(([id, label]) => (
            <div
              key={id}
              class={"tab" + (tab === id ? " active" : "")}
              onClick={() => setTab(id)}
            >
              {label}
            </div>
          ))}
        </div>
        <span class={"api " + (apiOk ? "ok" : "bad")}>
          API: <b>{apiOk ? "ok" : "offline"}</b>
        </span>
      </header>

      <CheckBanner check={check} error={checkErr} />

      <main>
        {projectErr ? (
          <div class="center-msg" style={{ gridColumn: "1 / -1" }}>
            <div>
              <p class="err-text">Could not reach the API: {projectErr}</p>
              <p class="hint">
                Start the backend (e.g. <code>dl2 studio</code> on{" "}
                <code>127.0.0.1:8788</code>), then reload.
              </p>
            </div>
          </div>
        ) : !project ? (
          <div class="center-msg" style={{ gridColumn: "1 / -1" }}>
            Loading project…
          </div>
        ) : (
          <>
            <Sidebar
              project={project}
              activeBeatId={activeBeatId}
              check={check}
              onSelect={setActiveBeatId}
            />
            <section class="pane">
              {beat ? (
                <>
                  <div class="panel-head">
                    <span class="title">{beat.title || beat.id}</span>
                    {beat.face && beat.face !== "none" && (
                      <span class="face-badge">{beat.face}</span>
                    )}
                    <span class="workflow">
                      <span
                        class={"step" + (beatTakes.length ? " done" : "")}
                      >
                        take
                      </span>
                      <span class={"step" + (beat.audio ? " done" : "")}>
                        audio
                      </span>
                      <span
                        class={
                          "step" +
                          (beat.rendered || renderPreview[beat.id]
                            ? " done"
                            : "")
                        }
                      >
                        render
                      </span>
                    </span>
                    <span class="spacer" />
                    <span class="action-status">{rInfo?.msg || ""}</span>
                    <button
                      class="btn"
                      disabled={rInfo?.state === "running"}
                      onClick={() => renderBeat(beat.id)}
                    >
                      {rInfo?.state === "running"
                        ? "Rendering…"
                        : "Render 540p draft"}
                    </button>
                  </div>

                  {tab === "script" && (
                    <ScriptTab
                      beat={beat}
                      irBeat={irBeat}
                      previewPath={previewPath}
                      previewToken={previewToken}
                    />
                  )}
                  {tab === "record" && (
                    <RecordTab
                      beat={beat}
                      takes={beatTakes}
                      addTake={addTake}
                      updateTake={updateTake}
                      onAfterProcess={afterProcess}
                    />
                  )}
                  {tab === "feedback" && (
                    <FeedbackPanel
                      beatId={beat.id}
                      feedback={feedback[beat.id]}
                    />
                  )}
                  {tab === "ir" && (
                    <IRInspector
                      ir={ir}
                      error={irErr}
                      activeBeatId={activeBeatId}
                    />
                  )}
                </>
              ) : (
                <div class="center-msg">Select a beat.</div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
