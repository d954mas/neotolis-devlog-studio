from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("analyze_rollout.py")
SPEC = importlib.util.spec_from_file_location("devlog_analyze_rollout", SCRIPT)
assert SPEC and SPEC.loader
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class AnalyzeRolloutCliTests(unittest.TestCase):
    def test_report_uses_utf8_when_windows_stdio_defaults_to_cp1251(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout-test.jsonl"
            event = {
                "timestamp": "2026-07-17T00:00:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "агент: before → after",
                },
            }
            rollout.write_text(
                json.dumps(event, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "cp1251:strict"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--rollout", str(rollout)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                result.stderr.decode("utf-8", errors="replace"),
            )
            self.assertIn("before → after", result.stdout.decode("utf-8"))

    def test_cwd_resolution_prefers_root_thread_over_newer_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex"
            workspace = Path(tmp) / "workspace"
            home.mkdir()
            workspace.mkdir()
            parent_rollout = home / "parent.jsonl"
            child_rollout = home / "child.jsonl"
            parent_rollout.write_text("", encoding="utf-8")
            child_rollout.write_text("", encoding="utf-8")

            database = sqlite3.connect(home / "state_test.sqlite")
            database.execute(
                "create table threads (id text, rollout_path text, cwd text, updated_at integer)"
            )
            database.execute(
                "create table thread_spawn_edges (parent_thread_id text, child_thread_id text)"
            )
            database.executemany(
                "insert into threads values (?, ?, ?, ?)",
                [
                    ("parent", str(parent_rollout), str(workspace), 1),
                    ("child", str(child_rollout), str(workspace), 2),
                ],
            )
            database.execute("insert into thread_spawn_edges values ('parent', 'child')")
            database.commit()
            database.close()

            thread_id, rollout = ANALYZER.latest_rollout_for_cwd(str(workspace), home)

            self.assertEqual(thread_id, "parent")
            self.assertEqual(rollout, parent_rollout)

    def test_report_counts_output_volume_without_printing_tool_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "rollout-output.jsonl"
            records = [
                {
                    "timestamp": "2026-07-17T00:00:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "call_id": "call-1",
                        "name": "exec",
                        "input": "inspect files",
                    },
                },
                {
                    "timestamp": "2026-07-17T00:00:01Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "call-1",
                        "output": "private first line\nprivate second line",
                    },
                },
            ]
            rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )

            rows, events, items, aborts, messages = ANALYZER.read_rollout(rollout)

            self.assertEqual(rows[0]["output_chars"], 38)
            self.assertEqual(rows[0]["output_lines"], 2)
            report = io.StringIO()
            with contextlib.redirect_stdout(report):
                ANALYZER.print_report(
                    rollout,
                    rows,
                    events,
                    items,
                    aborts,
                    messages,
                    top=3,
                )
            rendered = report.getvalue()
            self.assertIn("### Noisiest Calls", rendered)
            self.assertNotIn("private first line", rendered)


if __name__ == "__main__":
    unittest.main()
