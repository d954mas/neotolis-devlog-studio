import {
  closeSync,
  existsSync,
  mkdtempSync,
  openSync,
  readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";

const SCENARIOS = [
  "exact",
  "compare",
  "stale",
  "mismatch",
  "legacy",
  "same",
  "responsive",
];

const webuiRoot = resolve(import.meta.dirname, "..");
const repoRoot = resolve(webuiRoot, "../../..");
const localPython = resolve(
  webuiRoot,
  process.platform === "win32"
    ? "../.venv/Scripts/python.exe"
    : "../.venv/bin/python",
);

function pythonExecutable() {
  return process.env.DLSTUDIO_E2E_PYTHON ??
    (existsSync(localPython) ? localPython : "python");
}

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        server.close();
        reject(new Error("could not allocate an e2e port"));
        return;
      }
      const port = address.port;
      server.close(() => resolvePort(port));
    });
  });
}

async function waitForServer(url, child, logPath) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(
        `Studio fixture server exited ${child.exitCode}: ` +
          readFileSync(logPath, "utf8"),
      );
    }
    try {
      const response = await fetch(`${url}/api/v3/status`);
      if (response.ok) return;
    } catch {
      // The socket is not listening yet.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(
    `Studio fixture server did not start at ${url}: ` +
      readFileSync(logPath, "utf8"),
  );
}

export default async function globalSetup() {
  const root = mkdtempSync(join(tmpdir(), "dlstudio-e2e-"));
  const fixtureRoot = join(root, "fixtures");
  const python = pythonExecutable();
  const pythonPath = [
    repoRoot,
    resolve(repoRoot, "common/dlstudio/src"),
    process.env.PYTHONPATH,
  ]
    .filter(Boolean)
    .join(delimiter);
  const environment = {
    ...process.env,
    PYTHONPATH: pythonPath,
    PYTHONUTF8: "1",
    PYTHONDONTWRITEBYTECODE: "1",
  };
  const setup = spawnSync(
    python,
    [
      resolve(webuiRoot, "e2e/setup_review_fixtures.py"),
      "--root",
      fixtureRoot,
    ],
    {
      cwd: repoRoot,
      env: environment,
      encoding: "utf8",
      windowsHide: true,
    },
  );
  if (setup.status !== 0) {
    throw new Error(
      `fixture setup failed (${setup.status}): ${setup.stderr || setup.stdout}`,
    );
  }

  const ports = await Promise.all(SCENARIOS.map(() => freePort()));
  const servers = [];
  const baseURLs = {};
  try {
    for (let index = 0; index < SCENARIOS.length; index += 1) {
      const scenario = SCENARIOS[index];
      const port = ports[index];
      const logPath = join(root, `${scenario}.server.log`);
      const log = openSync(logPath, "a");
      const child = spawn(
        python,
        [
          "-m",
          "dlstudio",
          "--manifest",
          join(fixtureRoot, scenario, "production.toml"),
          "serve",
          "--port",
          String(port),
        ],
        {
          cwd: repoRoot,
          env: environment,
          stdio: ["ignore", log, log],
          windowsHide: true,
        },
      );
      closeSync(log);
      child.unref();
      const url = `http://127.0.0.1:${port}`;
      servers.push({ child, logPath });
      baseURLs[scenario] = url;
    }
    await Promise.all(
      servers.map(({ child, logPath }, index) =>
        waitForServer(baseURLs[SCENARIOS[index]], child, logPath),
      ),
    );
  } catch (error) {
    for (const { child } of servers) {
      if (child.exitCode === null) child.kill();
    }
    throw error;
  }

  process.env.DLSTUDIO_E2E_STATE = JSON.stringify({
    root,
    baseURLs,
    pids: servers.map(({ child }) => child.pid),
  });
}
