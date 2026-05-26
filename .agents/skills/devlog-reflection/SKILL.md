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

## Evidence To Gather

Read only what is needed:

- `AGENTS.md` and `common/PIPELINE.md` for intended workflow.
- Active project files: `devlog.toml`, `<project>/edits/<edit>/beats.py`, `<project>/data/review/feedback.json`, `<project>/data/publish/*`, `<project>/data/finalize/*`.
- Recent temporary review/contact-sheet files if they explain iteration pain.
- Git status/diff when code or prompts were changed.
- Conversation summary or available transcript when the reflection is about the current thread.
- Shell history/logs only if available locally and relevant.

If exact timing is unavailable, use observable sequence and file mtimes. Mark estimates as estimates.

## Reflection Workflow

1. **Scope**
   - Identify project, edit, main output file, and requested deliverable.
   - State what evidence was inspected.

2. **Timeline**
   - Build a compact timeline of phases: setup, script, recording, render, review, fixes, final packaging.
   - Note repeated loops, blocked steps, and handoffs to reviewer agents.

3. **What Went Fast**
   - List 3-7 things that were efficient.
   - Include why they were fast: cache, clear user feedback, reusable command, existing asset, good agent output.

4. **What Was Slow Or Painful**
   - List the bottlenecks ranked by time/impact.
   - For each: symptom, evidence, likely cause, and whether it was tool, process, prompt, asset, or decision quality.

5. **Missed Gates**
   - Identify checks that should have happened earlier: visual overlap audit, audio mix check, music attribution, thumbnail real-site validation, browser permission test, VO transition audit.

6. **Improvements**
   - Produce actionable changes grouped by:
     - **Agent prompt**: reviewer/designer/reflection agent changes.
     - **Skill/process**: checklist or playbook changes.
     - **CLI/Studio**: commands, automation, UI affordances.
     - **Assets/templates**: reusable thumbnails, music defaults, masks.
   - Each recommendation must include expected benefit and rough effort.

7. **Next Experiment**
   - Propose the smallest next-run experiment to validate the improvements.

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

### Missed Gates
- <gate> -> add <check/tool/prompt step>

### Improvements To Implement
| Area | Change | Benefit | Effort |
|---|---|---|---|

### Next Run Test
<one concrete experiment>
```

Keep the final reflection concise enough to act on. Move detailed logs into an appendix only if the user asks.
