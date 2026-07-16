"""services — plugins with lazy heavy dependencies. Phase 4 scope.

Planned: transcribe/ (WhisperX), audiofix/ (DeepFilterNet-class),
tts/ (sapi | piper | silero scratch VO), capture/ (CDP + obs-websocket),
stock/ (thin provider wrappers), publish/ (YouTube package generation).

Heavy imports happen inside functions, never at module import time.
"""
