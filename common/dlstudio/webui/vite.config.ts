import { defineConfig } from "vite";

// Studio v3 Web UI build config.
// - Preact JSX via esbuild's automatic runtime (no extra preset dependency).
// - Build output lands in the Python package's static dir so FastAPI can
//   serve it (`vite build --outDir` equivalent, set here).
// - `base: "./"` keeps asset URLs relative so the bundle works whether the
//   API mounts it at "/" or under "/static/".
// - Dev server proxies /api to the FastAPI dev server on 127.0.0.1:8788.
export default defineConfig({
  base: "./",
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "preact",
  },
  server: {
    port: 5175,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8788",
        changeOrigin: true,
      },
    },
  },
  build: {
    // Co-located with the thin v3 HTTP adapter that serves it.
    outDir: "../src/dlstudio/adapters/static",
    emptyOutDir: true,
    sourcemap: false,
  },
});
