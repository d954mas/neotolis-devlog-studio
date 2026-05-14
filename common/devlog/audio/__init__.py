"""Audio pipeline: ffmpeg loudness normalization + Whisper word-timestamp transcription."""
from .process import process_beat_audio
from .transcribe import transcribe
