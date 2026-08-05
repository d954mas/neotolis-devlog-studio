type StudioHeaderProps = {
  mode: "production" | "voice";
  reviewing: boolean;
  productionId?: string;
  busy: boolean;
  onMode: (mode: "production" | "voice") => void;
  onRefresh: () => void;
};

export function StudioHeader({ mode, reviewing, productionId, busy, onMode, onRefresh }: StudioHeaderProps) {
  const voice = mode === "voice";
  return (
    <header class={`topbar studio-topbar ${reviewing ? "review-topbar" : ""}`}>
      <div class="brand-lockup">
        <p class="eyebrow">DEVLOG STUDIO / V3</p>
        <h1>{voice ? "Запись голоса" : reviewing ? productionId : "Производство"}</h1>
      </div>
      <nav class="studio-nav" aria-label="Разделы студии">
        <button class={mode === "production" ? "nav-tab active" : "nav-tab"} aria-pressed={mode === "production"} onClick={() => onMode("production")}>Проект</button>
        <button class={voice ? "nav-tab active" : "nav-tab"} aria-pressed={voice} onClick={() => onMode("voice")}>Голос</button>
        <button class="quiet refresh-button" onClick={onRefresh} disabled={busy}>Обновить</button>
      </nav>
    </header>
  );
}
