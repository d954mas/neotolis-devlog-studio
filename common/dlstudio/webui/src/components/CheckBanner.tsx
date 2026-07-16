import { useState } from "preact/hooks";
import type { CheckReport } from "../api/types";

interface Props {
  check: CheckReport | null;
  error?: string | null;
}

export function CheckBanner({ check, error }: Props) {
  const [open, setOpen] = useState(false);

  if (error) {
    return (
      <div class="check-banner">
        <div class="summary">
          <span class="pill err">check unavailable</span>
          <span class="err-text">{error}</span>
        </div>
      </div>
    );
  }
  if (!check) {
    return (
      <div class="check-banner">
        <div class="summary">
          <span class="pill ok">checking…</span>
        </div>
      </div>
    );
  }

  const errors = check.issues.filter((i) => i.severity === "error");
  const warns = check.issues.filter((i) => i.severity === "warn");
  const clean = errors.length === 0 && warns.length === 0;

  return (
    <div class="check-banner">
      <div class="summary" onClick={() => setOpen((o) => !o)}>
        {clean ? (
          <span class="pill ok">no issues</span>
        ) : (
          <>
            {errors.length > 0 && (
              <span class="pill err">{errors.length} errors</span>
            )}
            {warns.length > 0 && (
              <span class="pill warn">{warns.length} warnings</span>
            )}
          </>
        )}
        {!clean && (
          <span class="caret">{open ? "▾ hide" : "▸ details"}</span>
        )}
      </div>
      {open && !clean && (
        <div class="issues">
          {check.issues.map((iss, i) => (
            <div class={`issue ${iss.severity}`} key={i}>
              <span class="sev">{iss.severity}</span>
              <span class="code">{iss.code}</span>
              <span class="msg">{iss.message}</span>
              <span class="where">{iss.where}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
