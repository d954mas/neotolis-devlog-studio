# Pre-publish checklist — vertical reel (Reels/TikTok/Shorts)

Source: post-run reflection on `trolley3d` (2026-07-17) — a 17.8s vertical
reel shipped with a resolution-check bypass and a platform-unsafe caption
position that the LEAD caught on delivery, not a reviewer or a script.
`dl2 preview` had never been run and `video-reviewer` had never been
spawned for that project; `data/review/` was empty at ship time. See
`AGENTS.md` "Reel defaults" for the numeric rules this checklist enforces
and `common/quality/VQ-RES.md` / `VQ-SAFE.md` for the underlying gates.

**Rule: run this checklist before every `dl2 final` on a vertical reel —
including under a stated deadline.** Section A below is not optional; it
is one CLI command plus looking at its output and costs about the same as
the `dl2 final` render you were about to run anyway. Section B is what you
may explicitly skip under real time pressure, but skipping it must be
**said out loud** in the handoff message, not silently dropped.

## A. Always run — no deadline excuses (~30–60s total)

These are cheap because the engine already does the check-as-gate work;
this section is "actually look at the output," not "do more rendering."

1. **`dl2 check <edit>`** is clean. If it isn't, you are not close to done
   regardless of the deadline.
2. **No VQ-RES bypass.** If `dl2 check`/`dl2 final` reports a `VQ-RES`
   upscale error on a full-bleed asset, the fix is **re-capture at the
   reel's orientation**, never a pre-crop/pre-upscale of the source in
   ffmpeg to silence the check. A worked-around VQ-RES error is not a
   passed check — see `common/quality/VQ-RES.md`.
3. **`dl2 preview <edit>`** — one command, produces
   `data/review/contact_sheet.jpg` (4×4 grid) and `data/review/keyframes/`.
   If `data/review/` does not exist or is stale (older than the current
   `beats.py`/asset changes) after this step, you have not done step 3.
4. **Look at the contact sheet** (Read the image) and check, against
   `AGENTS.md` "Platform-safe zones" and "Text placement":
   - Every overlay/caption sits with its vertical center in the
     **y ≈ 0.66–0.78** band (1272–1498px of 1920) and stays inside the
     centered **~900×1400px** cross-platform safe rectangle — not touching
     the literal bottom/top edge.
   - Nothing sits in the last ~450px from the bottom (Instagram caption +
     action-bar zone, the strictest platform) or the first ~220px from the
     top.
   - Nothing important is outside the **1080×1350 centered 4:5 rectangle**
     — Instagram's feed view crops to 4:5 and will cut anything outside it.
   - Text reads as anchored to the subject (under the footage/near the
     action), not floating alone in empty space.
5. **Read the transcript tokens.** Open every `data/**/*_words.json` feeding
   a caption/overlay and scan for garbled English/brand names — Whisper
   reliably mis-transcribes foreign proper nouns even in an otherwise
   correct RU transcript. Patch the specific word index, don't re-run
   transcription and hope. (Evidence: `trolley3d` — the game's English
   title came back as noise in `b01_words.json` and had to be patched by
   index before final.)
6. **Music license gate (lead directive, 2026-07-17).** Prefer CC0 /
   public-domain / purchased-no-attribution tracks when choosing music.
   If ANY track in the mix requires attribution (CC-BY / CC-BY-SA / free
   Kevin MacLeod etc.):
   - the attribution string is persisted to `data/publish/reel_caption.md`
     (or the platform package) **before** delivery, and
   - the delivery message contains a visible blocking warning — its own
     "⚠️ АТРИБУЦИЯ ОБЯЗАТЕЛЬНА" block with the exact copy-paste text —
     not a parenthetical note in prose. The lead must not be able to
     publish without seeing it. (Evidence: `trolley3d` r01 shipped to
     Instagram with no attribution because the requirement lived in
     passing chat text.)

## B. Skip only if you say so explicitly (state it in the handoff)

7. **`video-reviewer`** blind pass on the contact sheet/keyframes/MP4,
   verdict written to `data/review/feedback.json` with `artifact_path` +
   `artifact_sha256`. If truly skipped under deadline, say exactly that in
   the delivery message — "video-reviewer skipped, deadline" — so the gap
   is visible to whoever reads the handoff, not discovered later as
   "quality is bad."
8. **Ending check.** A deliberate final hold (title/CTA/site, ~1s), not an
   abrupt cut.

## Deadline-mode summary

If you truly have ~1 minute: do **A1–A5** only, and name what you skipped
from **B** in the delivery message. Do not silently substitute "I'll flag
it in passing text" for an actual gate — that already happened once (the
orchestrator noted the VQ-RES bypass and the skipped review in the
delivery message for `trolley3d` at first-draft time, and the project
still shipped three more times before the lead caught the same two issues
by eye). A note in prose is not a gate; a gate is something that blocks or
is explicitly declared skipped.
