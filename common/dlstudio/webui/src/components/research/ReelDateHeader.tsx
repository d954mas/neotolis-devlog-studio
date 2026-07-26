import { dateGroupLabel } from "./research-feed-dates";

interface ReelDateHeaderProps {
  publishedAt: string;
  count: number;
}

export function ReelDateHeader({ publishedAt, count }: ReelDateHeaderProps) {
  return (
    <div class="research-date-head">
      <h3>
        <time dateTime={publishedAt} title={new Date(publishedAt).toLocaleString()}>
          {dateGroupLabel(publishedAt)}
        </time>
      </h3>
      <span class="research-date-count" aria-label={`${count} Reels`}>{count}</span>
      <span class="research-date-rule" aria-hidden="true" />
    </div>
  );
}
