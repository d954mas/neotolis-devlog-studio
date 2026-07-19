import { useState } from "preact/hooks";
import type { ResearchAuthor, ReelInput } from "../../api/research";

interface ProjectFormProps {
  busy: boolean;
  onCreate: (input: { title: string; description: string; style_profile: string }) => Promise<boolean>;
}

export function ProjectForm({ busy, onCreate }: ProjectFormProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [style, setStyle] = useState("");

  async function submit(event: Event) {
    event.preventDefault();
    if (!title.trim()) return;
    if (!await onCreate({ title: title.trim(), description: description.trim(), style_profile: style.trim() })) return;
    setTitle("");
    setDescription("");
    setStyle("");
  }

  return (
    <form class="research-setup-form" onSubmit={submit}>
      <label class="field-label">Project name<input value={title} onInput={(e) => setTitle(e.currentTarget.value)} placeholder="Gamedev" required /></label>
      <label class="field-label">Research goal<textarea rows={2} value={description} onInput={(e) => setDescription(e.currentTarget.value)} placeholder="Learn how strong game-dev Reels build a story." /></label>
      <label class="field-label">Style profile<textarea rows={3} value={style} onInput={(e) => setStyle(e.currentTarget.value)} placeholder="Dry humour, real gameplay, concise captions…" /></label>
      <button class="btn" disabled={busy}>{busy ? "Creating…" : "Create project"}</button>
    </form>
  );
}

interface AuthorFormProps {
  busy: boolean;
  onCreate: (input: { username: string; display_name: string; followers_count: number | null; median_views: number | null }) => Promise<boolean>;
}

export function AuthorForm({ busy, onCreate }: AuthorFormProps) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [followers, setFollowers] = useState("");
  const [medianViews, setMedianViews] = useState("");

  async function submit(event: Event) {
    event.preventDefault();
    if (!username.trim()) return;
    if (!await onCreate({
      username: username.trim(),
      display_name: displayName.trim(),
      followers_count: followers ? Number(followers) : null,
      median_views: medianViews ? Number(medianViews) : null,
    })) return;
    setUsername("");
    setDisplayName("");
    setFollowers("");
    setMedianViews("");
  }

  return (
    <form class="research-inline-form" onSubmit={submit}>
      <label class="field-label">Instagram handle<input value={username} onInput={(e) => setUsername(e.currentTarget.value)} placeholder="@creator" required /></label>
      <label class="field-label">Name<input value={displayName} onInput={(e) => setDisplayName(e.currentTarget.value)} /></label>
      <label class="field-label">Followers<input type="number" min="0" value={followers} onInput={(e) => setFollowers(e.currentTarget.value)} /></label>
      <label class="field-label">Typical views<input type="number" min="0" value={medianViews} onInput={(e) => setMedianViews(e.currentTarget.value)} /></label>
      <button class="btn sm" disabled={busy}>{busy ? "Adding…" : "Add author"}</button>
    </form>
  );
}

interface ReferenceFormProps {
  authors: ResearchAuthor[];
  busy: boolean;
  onCreate: (input: ReelInput) => Promise<boolean>;
}

function defaultLocalTime(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function reelId(url: string): string {
  try {
    const parts = new URL(url).pathname.split("/").filter(Boolean);
    return parts.at(-1) || `reel-${Date.now()}`;
  } catch {
    return `reel-${Date.now()}`;
  }
}

export function ReferenceForm({ authors, busy, onCreate }: ReferenceFormProps) {
  const [authorId, setAuthorId] = useState(authors[0]?.id || "");
  const [url, setUrl] = useState("");
  const [published, setPublished] = useState(defaultLocalTime());
  const [views, setViews] = useState("");
  const [hook, setHook] = useState("");
  const [patterns, setPatterns] = useState("");

  const selected = authors.some((author) => author.id === authorId) ? authorId : authors[0]?.id || "";

  async function submit(event: Event) {
    event.preventDefault();
    if (!selected || !url.trim()) return;
    if (!await onCreate({
      id: reelId(url.trim()),
      author_id: selected,
      url: url.trim(),
      published_at: new Date(published).toISOString(),
      views: Number(views || 0),
      hook: hook.trim(),
      patterns: patterns.split(",").map((item) => item.trim()).filter(Boolean),
    })) return;
    setUrl("");
    setViews("");
    setHook("");
    setPatterns("");
  }

  return (
    <form class="research-inline-form reference-form" onSubmit={submit}>
      <label class="field-label">Author<select value={selected} onChange={(e) => setAuthorId(e.currentTarget.value)}>{authors.map((author) => <option key={author.id} value={author.id}>@{author.username}</option>)}</select></label>
      <label class="field-label wide">Reel URL<input type="url" value={url} onInput={(e) => setUrl(e.currentTarget.value)} placeholder="https://www.instagram.com/reel/…" required /></label>
      <label class="field-label">Published<input type="datetime-local" value={published} onInput={(e) => setPublished(e.currentTarget.value)} required /></label>
      <label class="field-label">Views<input type="number" min="0" value={views} onInput={(e) => setViews(e.currentTarget.value)} /></label>
      <label class="field-label wide">Hook<input value={hook} onInput={(e) => setHook(e.currentTarget.value)} placeholder="First spoken or on-screen promise" /></label>
      <label class="field-label wide">Patterns<input value={patterns} onInput={(e) => setPatterns(e.currentTarget.value)} placeholder="problem first, failure → fix" /></label>
      <button class="btn sm" disabled={busy}>{busy ? "Saving…" : "Save metric snapshot"}</button>
    </form>
  );
}
