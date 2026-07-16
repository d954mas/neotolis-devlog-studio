interface Props {
  label: string;
  db: number | null;
  /** dB above which the bar turns "hot". */
  hotDb?: number;
}

/** Map a dBFS value (~ -60..0) to a 0..100 fill percentage. */
function dbToPct(db: number): number {
  return Math.max(0, Math.min(100, (db + 60) * 1.6));
}

export function LevelMeter({ label, db, hotDb = -3 }: Props) {
  const pct = db == null ? 0 : dbToPct(db);
  const hot = db != null && db > hotDb;
  return (
    <div class="meter">
      <span>{label}</span>
      <div class="meter-bar">
        <div class={"fill" + (hot ? " hot" : "")} style={{ width: pct + "%" }} />
      </div>
      <span style={{ minWidth: "38px" }}>
        {db == null ? "—" : db.toFixed(1)}
      </span>
    </div>
  );
}
