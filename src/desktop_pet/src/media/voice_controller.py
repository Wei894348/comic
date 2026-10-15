"""Voice clip playback for local Ameath wav files."""

from __future__ import annotations

import random
import re
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import pygame

from src.constants import VOICE_DIR
from src.media.cosyvoice_tts import CosyVoiceTTS

if TYPE_CHECKING:
    from src.core.pet_core import DesktopPet


_SPEECH_PUNCTUATION = frozenset("，。！？；：、,.!?;:‘’“”'\"《》…")
_TEXT_COMPLETION_RATIO = 0.70


def sanitize_speech_text(text: str) -> str:
    """Remove markup and symbols that should not be sent to speech synthesis."""
    previous_text = ""
    while previous_text != text:
        previous_text = text
        text = re.sub(r"[（(][^()（）]*[）)]", " ", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_~#>|`]", " ", text)
    text = unicodedata.normalize("NFKC", text)

    cleaned_chars: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char.isspace():
            cleaned_chars.append(" ")
        elif category[0] in {"L", "N", "M"}:
            cleaned_chars.append(char)
        elif char in _SPEECH_PUNCTUATION:
            cleaned_chars.append(char)
        else:
            cleaned_chars.append(" ")

    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"([，。！？；：、,.!?;:])\1+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([，。！？；：、,.!?;:])", r"\1", cleaned)
    return " ".join(cleaned.split()).strip()


def typing_speed_for_audio(text: str, audio_duration_ms: int) -> int:
    character_count = max(1, len("".join(text.split())))
    target_duration_ms = audio_duration_ms * _TEXT_COMPLETION_RATIO
    return max(20, min(300, round(target_duration_ms / character_count)))


class VoiceController:
    """Play local clips and synthesize AI replies with CosyVoice."""

    STARTUP_CLIP = "现实系统，侵入完成.wav"

    def __init__(self, app: "DesktopPet") -> None:
        self.app = app
        self._clip_cache: dict[str, pygame.mixer.Sound] = {}
        self._last_click_clip = ""
        self._tts_busy = False
        self._cosyvoice = CosyVoiceTTS()

    def init_backend(self) -> None:
        if pygame.mixer.get_init():
            return
        try:
            pygame.mixer.init()
        except pygame.error as e:
            print(f"初始化语音模块失败: {e}")

    def play_startup(self) -> None:
        self.play_named(self.STARTUP_CLIP)

    def play_random_click(self) -> bool:
        return self.play_random_effect(show_text=True)

    def play_random_effect(self, show_text: bool = True) -> bool:
        """Play a random local voice effect, optionally without its filename text."""
        clips = [
            path.name
            for path in self._voice_dir().glob("*.wav")
            if path.name != self.STARTUP_CLIP
        ]
        if not clips:
            return False

        if len(clips) > 1 and self._last_click_clip in clips:
            clips.remove(self._last_click_clip)

        clip_name = random.choice(clips)
        self._last_click_clip = clip_name
        return self.play_named(clip_name, show_text=show_text)

    def speak_text(
        self,
        text: str,
        on_playback_start: Callable[[int], None] | None = None,
        on_failure: Callable[[], None] | None = None,
    ) -> bool:
        """Speak arbitrary text with CosyVoice only."""
        text = sanitize_speech_text(text)
        if not text or self._tts_busy or not self._cosyvoice.is_configured():
            return False

        self._tts_busy = True
        threading.Thread(
            target=self._speak_text_worker,
            args=(text, on_playback_start, on_failure),
            name="desktop-pet-tts",
            daemon=True,
        ).start()
        return True

    def _speak_text_worker(
        self,
        text: str,
        on_playback_start: Callable[[int], None] | None,
        on_failure: Callable[[], None] | None,
    ) -> None:
        playback_started = False

        def notify_playback_start(duration_ms: int) -> None:
            nonlocal playback_started
            playback_started = True
            if on_playback_start:
                self.app.root.after(0, lambda: on_playback_start(duration_ms))

        try:
            audio_data = self._cosyvoice.synthesize(text)
            self._play_generated_audio(audio_data, notify_playback_start)
        except Exception as e:
            print(f"CosyVoice 播放失败，已静音: {e}")
            if on_failure and not playback_started:
                self.app.root.after(0, on_failure)
        finally:
            self._tts_busy = False

    def _play_generated_audio(
        self,
        audio_data: bytes,
        on_playback_start: Callable[[int], None] | None = None,
    ) -> None:
        if not pygame.mixer.get_init():
            self.init_backend()
        if not pygame.mixer.get_init():
            raise RuntimeError("语音播放设备初始化失败")

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

            sound = pygame.mixer.Sound(temp_path)
            channel = pygame.mixer.find_channel(force=True)
            if channel is None:
                raise RuntimeError("没有可用的语音播放通道")
            channel.play(sound)
            self._active_tts_sound = sound
            if on_playback_start:
                on_playback_start(max(1, round(sound.get_length() * 1000)))
            while channel.get_busy():
                time.sleep(0.05)
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def play_named(self, filename: str, show_text: bool = True) -> bool:
        if not pygame.mixer.get_init():
            self.init_backend()
        if not pygame.mixer.get_init():
            return False

        path = self._voice_dir() / filename
        if not path.exists():
            return False

        try:
            sound = self._clip_cache.get(filename)
            if sound is None:
                sound = pygame.mixer.Sound(str(path))
                self._clip_cache[filename] = sound

            channel = pygame.mixer.find_channel(force=True)
            if channel is not None:
                channel.play(sound)
                if show_text:
                    text = path.stem.replace("_", " ")
                    duration = max(700, int(sound.get_length() * 1000) + 180)
                    self.app.speech_bubble.show(
                        text,
                        duration=duration,
                        allow_during_music=True,
                    )
                return True
        except pygame.error as e:
            print(f"播放语音失败 {filename}: {e}")
        return False

    def stop(self) -> None:
        try:
            for channel_index in range(pygame.mixer.get_num_channels()):
                pygame.mixer.Channel(channel_index).stop()
        except pygame.error:
            pass

    def _voice_dir(self) -> Path:
        return VOICE_DIR
