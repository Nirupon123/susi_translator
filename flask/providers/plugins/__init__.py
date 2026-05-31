from providers.registry import register_provider
from .transcription_plugins.whisper_local import WhisperLocalProvider
from .translation_plugins.nllb_local import NLLBLocalProvider



#register the providers for transcription only
register_provider(
    "whisper_local", 
    factory=lambda config: WhisperLocalProvider(config)
)



#register the providers for translation only
register_provider(
    "nllb_local",
    factory=lambda config: NLLBLocalProvider(config)
)