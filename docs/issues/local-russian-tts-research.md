# Research local neural Russian TTS for scratch voiceovers

## Context

We added a very simple local scratch TTS path via Windows SAPI:

- CLI: `dl scratch-tts`
- Current available Russian voice on the workstation: `Microsoft Irina Desktop` (`ru-RU`)
- Output: `data/scratch/<beat>_scratch_tts.wav`
- Purpose: rough timing and pacing checks before recording real VO

This is good enough as a zero-dependency baseline, but quality is system-dictation level. We may want to revisit neural local TTS later if setup remains simple and fast.

## Candidates to evaluate later

- **Silero TTS**
  - Strong Russian support, multiple speakers: `aidar`, `baya`, `kseniya`, `xenia`, `eugene`
  - Supports Russian-specific stress/homograph handling in v5 models
  - Requires PyTorch/model download, so not zero-dependency
  - License details need checking before use in production/commercial output

- **Piper TTS**
  - Fast local ONNX-based TTS
  - Russian voices available via `rhasspy/piper-voices`: `denis`, `dmitri`, `irina`, `ruslan`
  - Model set is relatively small per voice
  - Original `rhasspy/piper` repo is archived; check current maintained fork/tooling before integrating

- **RHVoice**
  - Mature Russian offline TTS / SAPI-compatible option
  - Likely easy on Windows, but quality may be closer to classic screen-reader voices than neural VO

- **Kokoro / HyperFrames TTS**
  - Already present in HyperFrames media workflow, but current documented voice languages do not include Russian, so not a candidate for Russian scratch VO right now

## Acceptance Criteria

Only integrate a new local TTS backend if it is:

- simple to install or bootstrap from `dl`;
- fast enough on the current PC for short beat previews;
- supports Russian text well enough for rough timing;
- can output WAV reliably;
- does not require cloud API keys;
- keeps generated scratch audio out of git;
- remains optional, with Windows SAPI as the fallback baseline.

## Possible CLI Shape

```powershell
dl scratch-tts b04 --backend sapi
dl scratch-tts b04 --backend piper --voice ruslan
dl scratch-tts b04 --backend silero --voice aidar
```

## References

- Silero Models: https://github.com/snakers4/silero-models
- Piper: https://github.com/rhasspy/piper
- Piper Russian voices: https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU
- RHVoice Russian voices: https://rhvoice.org/ru-voices/
