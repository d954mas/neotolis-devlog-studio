"""Studio v3 Python authoring DSL."""

from .api import (
    Animation,
    AudioClip,
    Edit,
    MediaLayer,
    SolidLayer,
    TextLayer,
    VideoFade,
)
from .compiler import compile_edit

__all__ = [
    "Animation",
    "AudioClip",
    "Edit",
    "MediaLayer",
    "SolidLayer",
    "TextLayer",
    "VideoFade",
    "compile_edit",
]
