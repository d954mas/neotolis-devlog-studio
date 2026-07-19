import { ResearchLab } from "./ResearchLab";

export function ResearchApp() {
  return (
    <div class="research-app">
      <header class="research-topbar">
        <div class="research-title-lockup">
          <a href="/" class="research-studio-mark" aria-label="Open video production Studio">
            <span class="dot" aria-hidden="true">●</span> Studio
          </a>
          <span class="research-divider" aria-hidden="true">/</span>
          <div>
            <span class="eyebrow">Content intelligence</span>
            <h1>Pattern Lab</h1>
          </div>
        </div>
        <p>Study what works. Test the pattern without losing your voice.</p>
        <a class="btn sm secondary research-studio-link" href="/">Video Studio</a>
      </header>
      <main class="research-workspace">
        <ResearchLab />
      </main>
    </div>
  );
}
