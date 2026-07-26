# Studio v3 verification harness

The harness is deliberately outside the importable runtime package:

```powershell
python -m tools.studio_v3_verify --profile auto --scope full
```

`auto` uses the Phase 0 profile while any configured legacy runtime path is
present. Once every listed path is removed it becomes the strict `cutover`
profile, which additionally blocks legacy surfaces and requires a deterministic
`generate:client` Web UI script. Final cutover verification should also be run
explicitly:

```powershell
python -m tools.studio_v3_verify --profile cutover --scope full
```

Scopes:

- `static`: toolchain, dependency boundaries, banned surfaces, canonical
  vectors, and performance-hook contracts.
- `gates`: static gates, focused `tests/v3_gates`, generated-client
  cleanliness, and Web UI tests/build.
- `full`: static gates, the complete dlstudio regression suite,
  generated-client cleanliness, and Web UI tests/build.

The runner injects a process-local Git `safe.directory` entry. It never changes
global Git configuration. Python CI dependencies are frozen in
`python-ci.lock`; Node dependencies use the Web UI `package-lock.json`.

