---
name: devlog-thumbnail
description: Create, composite, and review YouTube thumbnails for devlog videos. Use when a user asks for a video thumbnail, cover image, YouTube package art, "icon for the video", or wants AI art combined with real product/site screenshots, including QA for readability, click appeal, real-product accuracy, green-screen masking, laptop/screen compositing, and feed-size previews.
---

# Devlog Thumbnail

Use this skill for YouTube thumbnail work around devlog videos. The thumbnail is a separate deliverable from the video: it needs its own brief, design pass, product-proof layer, and feed-size QA.

## Core Rules

1. Use real product visuals for the product area. Do not ask an image model to invent the site UI when the user wants their actual service shown.
2. Keep AI art and real screenshots as separate layers whenever possible: AI background/text/props first, product screenshot composited afterward.
3. Optimize for feed readability, not full-size beauty. Check at 320x180 and 160x90 before calling it done.
4. Keep text short. Target 1-4 words in the main hook and at most one small supporting phrase.
5. Keep critique independent. A thumbnail critic should do a blind review first; the orchestrator should run regression gates from prior user corrections afterward.
6. Prefer a strong simple composition over many details: face/object or product proof, one title, one contrast area, one directional cue.

## Workflow

### 1. Brief

Collect or infer:

- video topic and promise
- target viewer and emotion: curiosity, "I need this", progress, surprise
- required real screenshot or product visual
- words that must appear, if any
- style direction from existing drafts or user feedback
- constraints: no fake UI, no excess text, no green spill, screenshot must fit the device frame

If the user gives a concrete direction, execute it instead of re-briefing.

For review-only requests, do not load prior user corrections into the reviewer. First produce the blind verdict. Then the orchestrator may separately compare the result against known regression gates such as fake UI, green spill, excessive text, or product screenshot too small.

### 2. Source Assets

Find or create:

- latest real screenshot from the product/site/video frame
- AI-generated art or background if requested
- optional screenshot crop for laptop/monitor/phone screen
- prior thumbnail drafts for continuity

For AI generation, keep the prompt explicit: reserve a clean screen area, green/transparent placeholder if needed, no invented interface details in the product display area.

### 3. Composition Plan

Choose one layout:

- **Split proof:** left hook text + right real product screenshot.
- **Device insert:** AI scene with laptop/monitor, then perspective-warp real screenshot into the device.
- **Before/after:** old visual vs new visual, only if the story is about redesign.
- **Dashboard proof:** product screenshot dominates, with one punchy text block.

For the Neotolis diary style, prefer: bold left hook, small chips like Reddit/YouTube/posts, real site screenshot on the right, warm high-contrast accents, and a readable URL or product name only if it stays clean at small size.

### 4. AI Art Pass

If using image generation:

- Ask for the non-product parts only: title treatment, background, objects, lighting, chips, device frame.
- Use a bright placeholder screen if the real screenshot will be inserted later.
- Avoid tiny UI text inside generated art.
- Keep enough blank/low-detail area behind the title.

### 5. Product Composite

When placing a real screenshot into a generated laptop/monitor:

- Perspective-warp the screenshot to the screen corners.
- Crop to fill the screen without losing the important product area.
- Slightly darken or grade the screenshot only enough to match lighting.
- Mask inside the screen border; inspect edges for green spill or screenshot leakage.
- Do not let decorative device borders hide the product's primary UI.

### 6. QA Gates

Before showing the thumbnail as final, check:

- real product visual is visible and recognizable
- title readable at 320x180 and still roughly readable at 160x90
- no fake UI appears where the user expects their site
- no green/placeholder color leaks around screen edges
- screenshot is not too small or over-cropped
- text does not collide with borders, chips, device frames, or decorative lines
- thumbnail still makes sense without the video title
- final file is 16:9 and at least 1280x720 for upload

Run the contact-sheet helper when possible:

```powershell
python .agents/skills/devlog-thumbnail/scripts/thumbnail_contact_sheet.py <thumbnail.png> --out <thumbnail>_contact.png
```

Open the contact sheet and inspect small sizes before finalizing.

## Reviewer Agent Output

When reviewing a thumbnail, return:

```markdown
### Thumbnail Review

**Verdict:** ship / revise

**What works:**
- <specific point>

**Blocking issues:**
1. <issue> at <area> -> <specific fix>

**Small-size read:**
- 320x180: <readable/not readable>
- 160x90: <readable/not readable>

**Next edit:**
<one concrete action>
```

Keep feedback short and ranked. The goal is to converge quickly, not to list every possible aesthetic preference.
