---
name: devlog-reflection
description: Run a post-production reflection for devlog/video pipeline work. Use when the user asks for reflection, postmortem, retrospective, "рефлексия", "разбор после работы", to find slow or problematic places, compare expected vs actual workflow, and propose concrete improvements to agents, skills, scripts, Studio, or the devlog pipeline after creating or iterating a video.
---

# Devlog Reflection

Reflect on a completed or interrupted devlog production run using evidence first, then recommendations. The goal is to improve the next run, not to narrate the whole session.

## Core Rules

1. Ground every finding in a concrete artifact: command output, file path, rendered video, screenshot, review feedback, user correction, or timestamped dialogue event.
2. Separate symptoms from causes. "Music was wrong" is a symptom; "no music selection gate before mix" is a cause.
3. Prefer workflow fixes over vague advice. Name the agent, skill, script, UI, command, or checklist that should change.
4. Preserve what worked. Fast paths matter as much as failures.
5. Do not blame the user for missing context. If the process needed context, propose a capture step or checklist.
6. Compare the run with the user's stated budgets. For the current long-form devlog baseline, track both **2–3 hours total wall time** and **20–30 minutes of human time** for recording plus review.
7. Keep quality review and process reflection separate: `video-reviewer` judges the artifact; this skill diagnoses how the artifact was produced.

## Evidence To Gather

Read only what is needed:

- `AGENTS.md` and `common/PIPELINE.md` for intended workflow.
- Active project files: `devlog.toml`, `<project>/edits/<edit>/beats.py`, `<project>/data/review/feedback.json`, `<project>/data/publish/*`, `<project>/data/finalize/*`.
- Recent temporary review/contact-sheet files if they explain iteration pain.
- Git status/diff when code or prompts were changed.
- Conversation summary or available transcript when the reflection is about the current thread.
- Shell history/logs only if available locally and relevant.
- Codex rollout logs when available: `~/.codex/sessions/**/rollout-*.jsonl`, plus `~/.codex/state_*.sqlite` to resolve thread ids and child agents.
- Tool timing evidence: tool counts, slowest calls, shell wall-time, response latency, `wait_agent` time, subagent threads, aborted turns, context compactions.
- User feedback loop evidence: repeated corrections from `user_message` events, grouped by category. Use this for orchestrator regression gates, not as context for blind reviewer agents.

If exact timing is unavailable, use observable sequence and file mtimes. Mark estimates as estimates.

## Tool Timing Audit

Run this before writing bottlenecks when a Codex rollout file is available:

```powershell
python .agents/skills/devlog-reflection/scripts/analyze_rollout.py --cwd C:\projects\devlogs --children
```

Prefer an exact root thread id when it is available. `--cwd` deliberately
selects the newest root task rather than a newer child agent, then `--children`
adds the delegated work. Always verify the printed rollout path before using
the report as evidence.

Useful variants:

```powershell
python .agents/skills/devlog-reflection/scripts/analyze_rollout.py --thread-id <thread-id> --children
python .agents/skills/devlog-reflection/scripts/analyze_rollout.py --rollout C:\Users\ROG\.codex\sessions\...\rollout-....jsonl
```

Use the report to answer:

- Which tools were used most: shell, browser, image generation, patching, subagents, web search.
- Where the agent actually waited: command wall-time, response latency, `wait_agent`, image generation, web downloads, browser capture.
- Whether time was spent in useful compute or orchestration overhead. If latency is much higher than wall-time, call that out as waiting on wrapper/approval/model rather than the command itself.
- Treat `orchestration/session gap` separately from productive work. It usually means an interrupted turn, resume, approval gap, or wrapper delay, not that the underlying tool was slow.
- Which subagents ran, how long the parent waited for them, and whether their own tool usage was heavy or mostly model reasoning.
- Whether repeated tool calls indicate a missing pipeline primitive, for example repeated website capture, repeated Hyperframes lint/render, or repeated thumbnail compositing.
- Which calls produced the most output characters/lines. Treat a large image
  payload or recursive file listing as context cost, not command wall time;
  recommend a narrower query or preview when the extra output was unused.

## User Feedback Loop Audit

The rollout analyzer also prints `User Feedback Loops` and `Repeated Corrections`. Use this to identify places where the user had to correct the same issue repeatedly.

Classify each repeated correction as one of:

- **Deterministic missed gate:** should be caught by a script/checklist, for example missing music, text overlapping lines, fake product UI, green-screen leak, no ending, unavailable record button.
- **Preference calibration:** needed user taste, for example music mood, thumbnail style, exact amount of visual energy.
- **Discovery/input issue:** required fresh access or user action, for example browser session, microphone permission, production preview loading.

Do not pass this correction history to `video-reviewer`, `vo-reviewer`, or `thumbnail-designer` in critique mode. Critics should stay blind. The orchestrator uses feedback loops after the blind review as a separate regression checklist.

## Reflection Workflow

1. **Scope**
   - Identify project, edit, main output file, and requested deliverable.
   - State what evidence was inspected.

2. **Timeline**
   - Build a compact timeline of phases: setup, script, recording, render, review, fixes, final packaging.
   - Note repeated loops, blocked steps, and handoffs to reviewer agents.
   - Add a timing layer from rollout logs when available: top wait categories, longest calls, and subagent waits.

3. **What Went Fast**
   - List 3-7 things that were efficient.
   - Include why they were fast: cache, clear user feedback, reusable command, existing asset, good agent output.

4. **What Was Slow Or Painful**
   - List the bottlenecks ranked by time/impact.
   - For each: symptom, evidence, likely cause, and whether it was tool, process, prompt, asset, or decision quality.

5. **Missed Gates**
   - Identify checks that should have happened earlier: visual overlap audit, audio mix check, music attribution, thumbnail real-site validation, browser permission test, VO transition audit.
   - Convert repeated user corrections into explicit gates owned by orchestrator, CLI/Studio, or a specialized skill.

6. **Improvements**
   - Produce actionable changes grouped by:
     - **Agent prompt**: reviewer/designer/reflection agent changes.
     - **Skill/process**: checklist or playbook changes.
     - **CLI/Studio**: commands, automation, UI affordances.
     - **Assets/templates**: reusable thumbnails, music defaults, masks.
   - Each recommendation must include expected benefit and rough effort.

7. **Next Experiment**
   - Propose the smallest next-run experiment to validate the improvements.

8. **Persist And Promote Carefully**
   - Save the reflection to
     `<project>/data/review/reflections/<YYYY-MM-DDTHH-MM-SS>_<edit>.md`.
   - Include the exact rollout/thread id, output artifact path and SHA-256 when
     an artifact exists, target budgets, and actual known human/wall time.
   - Keep one-run observations in the reflection. Promote a change into an
     owning skill/checklist only when it is a deterministic missed gate, has
     repeated, or has an obviously large measured payoff. Route engine work to
     `docs/issues/`; do not silently redesign the pipeline from one run.

9. **Follow Up On Outcome**
   - Immediate reflection covers production speed and artifact quality.
   - A separate 48-hour / 7-day follow-up may compare YouTube retention and
     engagement with Neotolis Diary posts, clicks, and wishlist movement. Do
     not treat production telemetry as proof that the video performed well.

## Output Format

Use this structure:

```markdown
## Reflection

**Scope:** <project/edit/output>
**Evidence:** <files/logs/dialogue inspected>

### Timeline
| Phase | What happened | Friction |
|---|---|---|

### Worked Well
- <fact-backed point>

### Slow / Problematic
1. **<bottleneck>** — evidence: <artifact>. Cause: <cause>. Fix: <specific change>.

### Tool Timing
| Category | Calls | Wall Time | Latency | Interpretation |
|---|---:|---:|---:|---|

### User Feedback Loops
| Category | Repeats | What It Means | Prevention |
|---|---:|---|---|

### Missed Gates
- <gate> -> add <check/tool/prompt step>

### Improvements To Implement
| Area | Change | Benefit | Effort |
|---|---|---|---|

### Next Run Test
<one concrete experiment>
```

Rank at most three improvements for the next run. Keep the final reflection concise enough to act on. Move detailed logs into an appendix only if the user asks.
