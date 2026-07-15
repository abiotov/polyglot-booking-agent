"""Speech providers: STT and TTS behind swappable interfaces.

Public API:

    from speech import DeepgramSTT, CartesiaTTS
    from speech.types import STTProvider, TTSProvider, Utterance, AudioClip
"""

from .cartesia_tts import CartesiaTTS
from .deepgram_stt import DeepgramSTT
from .types import AudioClip, STTProvider, TTSProvider, Utterance

__all__ = [
    "AudioClip",
    "CartesiaTTS",
    "DeepgramSTT",
    "STTProvider",
    "TTSProvider",
    "Utterance",
]
