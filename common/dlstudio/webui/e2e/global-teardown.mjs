import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, resolve } from "node:path";

function isRunning(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export default async function globalTeardown() {
  const raw = process.env.DLSTUDIO_E2E_STATE;
  if (!raw) return;
  const state = JSON.parse(raw);
  for (const pid of state.pids ?? []) {
    try {
      process.kill(pid);
    } catch {
      // A server that already stopped needs no cleanup.
    }
  }
  const deadline = Date.now() + 5_000;
  while (
    Date.now() < deadline &&
    (state.pids ?? []).some((pid) => isRunning(pid))
  ) {
    await new Promise((resolveWait) => setTimeout(resolveWait, 50));
  }
  const remaining = (state.pids ?? []).filter((pid) => isRunning(pid));
  if (remaining.length > 0) {
    throw new Error(
      `Studio fixture servers did not terminate: ${remaining.join(", ")}`,
    );
  }
  const root = resolve(state.root);
  const temporaryParent = resolve(tmpdir());
  if (
    dirname(root) !== temporaryParent ||
    !basename(root).startsWith("dlstudio-e2e-")
  ) {
    throw new Error(`refusing unsafe e2e cleanup target: ${root}`);
  }
  rmSync(root, { recursive: true, force: true, maxRetries: 5 });
}
