import type { ResearchReel } from "../../api/research";

export function compactMetric(value: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function metricFreshness(hours: number): string {
  if (hours < 1) return "metrics updated <1h ago";
  if (hours < 48) return `metrics updated ${Math.round(hours)}h ago`;
  return `metrics updated ${Math.round(hours / 24)}d ago`;
}

export function readableText(value: string): string {
  return value
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/(^|\s)#\S+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function reelCopy(reel: ResearchReel): {
  label: "Hook" | "Caption";
  title: string;
  description: string;
} {
  const hook = readableText(reel.hook || "");
  const caption = readableText(reel.caption || "");

  if (hook) {
    return {
      label: "Hook",
      title: hook,
      description: caption && caption !== hook ? caption : "",
    };
  }

  if (!caption) {
    return {
      label: "Caption",
      title: "No caption captured yet.",
      description: "",
    };
  }

  const firstSentence = caption.match(/^.{1,140}?[.!?](?:\s|$)/)?.[0]?.trim();
  const title = firstSentence || caption;
  return {
    label: "Caption",
    title,
    description: caption.startsWith(title) ? caption.slice(title.length).trim() : caption,
  };
}

// Mirrors the compact date buckets used by Neotolis Diary's feed.
export function formatFeedDate(input: string, now = new Date()): string {
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return "—";

  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) {
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    return `Today, ${hh}:${mm}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate()
  ) {
    return "Yesterday";
  }

  return date.toLocaleDateString("en", {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}
