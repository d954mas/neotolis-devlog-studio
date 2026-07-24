import type { ResearchReel } from "../../api/research";
import { formatFeedDate } from "./reel-card-format";

export interface ResearchDateGroup {
  date: string;
  publishedAt: string;
  reels: ResearchReel[];
}

export function groupReelsByDate(reels: ResearchReel[]): ResearchDateGroup[] {
  const groups: ResearchDateGroup[] = [];
  let current: ResearchDateGroup | null = null;

  for (const reel of reels) {
    const date = new Date(reel.published_at);
    const key = Number.isNaN(date.getTime())
      ? reel.published_at
      : [
          date.getFullYear(),
          String(date.getMonth() + 1).padStart(2, "0"),
          String(date.getDate()).padStart(2, "0"),
        ].join("-");
    if (!current || current.date !== key) {
      current = { date: key, publishedAt: reel.published_at, reels: [] };
      groups.push(current);
    }
    current.reels.push(reel);
  }

  return groups;
}

export function dateGroupLabel(input: string, now = new Date()): string {
  const label = formatFeedDate(input, now);
  return label.startsWith("Today") ? "Today" : label;
}
