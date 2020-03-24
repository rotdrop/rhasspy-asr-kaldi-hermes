"""Unit tests for rhasspyasr_kaldi_hermes"""
import asyncio
import json
import logging
import secrets
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from rhasspyasr import Transcription
from rhasspyasr_kaldi_hermes import AsrHermesMqtt
from rhasspyhermes.asr import (
    AsrAudioCaptured,
    AsrStartListening,
    AsrStopListening,
    AsrTextCaptured,
    AsrError,
    AsrTrain,
    AsrTrainSuccess,
)
from rhasspyhermes.audioserver import AudioFrame
from rhasspyhermes.g2p import G2pPronounce, G2pPronunciation, G2pPhonemes, G2pError

_LOGGER = logging.getLogger(__name__)
_LOOP = asyncio.get_event_loop()

# -----------------------------------------------------------------------------


class FakeException(Exception):
    """Exception used for testing."""

    pass


# -----------------------------------------------------------------------------


class RhasspyAsrKaldiHermesTestCase(unittest.TestCase):
    """Tests for rhasspyasr_kaldi_hermes"""

    def setUp(self):
        self.siteId = str(uuid.uuid4())
        self.sessionId = str(uuid.uuid4())

        self.client = MagicMock()
        self.transcriber = MagicMock()

        self.hermes = AsrHermesMqtt(
            self.client,
            lambda: self.transcriber,
            model_dir=Path("."),
            graph_dir=Path("."),
            no_overwrite_train=True,
            g2p_model=Path("fake-g2p.fst"),
            siteIds=[self.siteId],
            loop=_LOOP,
        )

        # No conversion
        self.hermes.convert_wav = lambda wav_bytes, **kwargs: wav_bytes

    def tearDown(self):
        self.hermes.stop()

    # -------------------------------------------------------------------------

    async def async_test_session(self):
        """Check good start/stop session."""
        fake_transcription = Transcription(
            text="this is a test", likelihood=1, transcribe_seconds=0, wav_seconds=0
        )

        def fake_transcribe(stream, *args):
            """Return test trancription."""
            for chunk in stream:
                if not chunk:
                    break

            return fake_transcription

        self.transcriber.transcribe_stream = fake_transcribe

        # Start session
        start_listening = AsrStartListening(
            siteId=self.siteId,
            sessionId=self.sessionId,
            stopOnSilence=False,
            sendAudioCaptured=True,
        )
        result = None
        async for response in self.hermes.on_message(start_listening):
            result = response

        # No response expected
        self.assertIsNone(result)

        # Send in "audio"
        fake_wav_bytes = self.hermes.to_wav_bytes(secrets.token_bytes(100))
        fake_frame = AudioFrame(wav_bytes=fake_wav_bytes)
        async for response in self.hermes.on_message(fake_frame, siteId=self.siteId):
            result = response

        # No response expected
        self.assertIsNone(result)

        # Stop session
        stop_listening = AsrStopListening(siteId=self.siteId, sessionId=self.sessionId)

        results = []
        async for response in self.hermes.on_message(stop_listening):
            results.append(response)

        # Check results
        self.assertEqual(
            results,
            [
                AsrTextCaptured(
                    text=fake_transcription.text,
                    likelihood=fake_transcription.likelihood,
                    seconds=fake_transcription.transcribe_seconds,
                    siteId=self.siteId,
                    sessionId=self.sessionId,
                ),
                (
                    AsrAudioCaptured(wav_bytes=fake_wav_bytes),
                    {"siteId": self.siteId, "sessionId": self.sessionId},
                ),
            ],
        )

    def test_session(self):
        """Call async_test_session."""
        _LOOP.run_until_complete(self.async_test_session())

    # -------------------------------------------------------------------------

    async def async_test_transcriber_error(self):
        """Check start/stop session with error in transcriber."""
        fake_transcription = Transcription(
            text="this is a test", likelihood=1, transcribe_seconds=0, wav_seconds=0
        )

        def fake_transcribe(stream, *args):
            """Raise an exception."""
            raise FakeException()

        self.transcriber.transcribe_stream = fake_transcribe

        # Start session
        start_listening = AsrStartListening(
            siteId=self.siteId, sessionId=self.sessionId, stopOnSilence=False
        )
        result = None
        async for response in self.hermes.on_message(start_listening):
            result = response

        # No response expected
        self.assertIsNone(result)

        # Send in "audio"
        fake_wav_bytes = self.hermes.to_wav_bytes(secrets.token_bytes(100))
        fake_frame = AudioFrame(wav_bytes=fake_wav_bytes)
        async for response in self.hermes.on_message(fake_frame, siteId=self.siteId):
            result = response

        # No response expected
        self.assertIsNone(result)

        # Stop session
        stop_listening = AsrStopListening(siteId=self.siteId, sessionId=self.sessionId)

        results = []
        async for response in self.hermes.on_message(stop_listening):
            results.append(response)

        # Check results for empty transcription
        self.assertEqual(
            results,
            [
                AsrTextCaptured(
                    text="",
                    likelihood=0,
                    seconds=0,
                    siteId=self.siteId,
                    sessionId=self.sessionId,
                )
            ],
        )

    def test_transcriber_error(self):
        """Call async_test_error."""
        _LOOP.run_until_complete(self.async_test_transcriber_error())

    # -------------------------------------------------------------------------

    async def async_test_silence(self):
        """Check start/stop session with silence detection."""
        fake_transcription = Transcription(
            text="turn on the living room lamp",
            likelihood=1,
            transcribe_seconds=0,
            wav_seconds=0,
        )

        def fake_transcribe(stream, *args):
            """Return test trancription."""
            for chunk in stream:
                if not chunk:
                    break

            return fake_transcription

        self.transcriber.transcribe_stream = fake_transcribe

        # Start session
        start_listening = AsrStartListening(
            siteId=self.siteId,
            sessionId=self.sessionId,
            stopOnSilence=True,
            sendAudioCaptured=False,
        )
        result = None
        async for response in self.hermes.on_message(start_listening):
            result = response

        # No response expected
        self.assertIsNone(result)

        # Send in "audio"
        wav_path = Path("etc/turn_on_the_living_room_lamp.wav")

        results = []
        with open(wav_path, "rb") as wav_file:
            for wav_bytes in AudioFrame.iter_wav_chunked(wav_file, 4096):
                frame = AudioFrame(wav_bytes=wav_bytes)
                async for response in self.hermes.on_message(frame, siteId=self.siteId):
                    results.append(response)

        # Except transcription
        self.assertEqual(
            results,
            [
                AsrTextCaptured(
                    text=fake_transcription.text,
                    likelihood=fake_transcription.likelihood,
                    seconds=fake_transcription.transcribe_seconds,
                    siteId=self.siteId,
                    sessionId=self.sessionId,
                )
            ],
        )

    def test_silence(self):
        """Call async_test_silence."""
        _LOOP.run_until_complete(self.async_test_silence())

    # -------------------------------------------------------------------------

    async def async_test_train_success(self):
        """Check successful training."""
        train = AsrTrain(id=self.sessionId, graph_path="fake.pickle.gz")

        # Send in training request
        result = None
        async for response in self.hermes.on_message(train, siteId=self.siteId):
            result = response

        self.assertEqual(
            result, (AsrTrainSuccess(id=self.sessionId), {"siteId": self.siteId})
        )

    def test_train_success(self):
        """Call async_test_train_success."""
        _LOOP.run_until_complete(self.async_test_train_success())

    # -------------------------------------------------------------------------

    async def async_test_train_error(self):
        """Check training error."""

        # Force a training error
        self.hermes.model_dir = None
        train = AsrTrain(id=self.sessionId, graph_path="fake.pickle.gz")

        # Send in training request
        result = None
        async for response in self.hermes.on_message(train, siteId=self.siteId):
            result = response

        self.assertIsInstance(result, AsrError)
        self.assertEqual(result.siteId, self.siteId)
        self.assertEqual(result.sessionId, self.sessionId)

    def test_train_error(self):
        """Call async_test_train_error."""
        _LOOP.run_until_complete(self.async_test_train_error())

    # -------------------------------------------------------------------------

    async def async_test_g2p_pronounce(self):
        """Check guessed pronunciations."""
        num_guesses = 2
        fake_words = ["foo", "bar"]
        fake_phonemes = ["P1", "P2", "P3"]

        def fake_guess(words, *args, num_guesses=0, **kwargs):
            """Generate fake phonetic pronunciations."""
            for word in words:
                for _ in range(num_guesses):
                    yield word, fake_phonemes

        with patch("rhasspynlu.g2p.guess_pronunciations", new=fake_guess):
            g2p_id = str(uuid.uuid4())
            pronounce = G2pPronounce(
                id=g2p_id,
                words=fake_words,
                numGuesses=num_guesses,
                siteId=self.siteId,
                sessionId=self.sessionId,
            )

            # Send in request
            result = None
            async for response in self.hermes.on_message(pronounce):
                result = response

        expected_prons = [
            G2pPronunciation(phonemes=fake_phonemes, guessed=True)
            for _ in range(num_guesses)
        ]

        self.assertEqual(
            result,
            G2pPhonemes(
                id=g2p_id,
                wordPhonemes={word: expected_prons for word in fake_words},
                siteId=self.siteId,
                sessionId=self.sessionId,
            ),
        )

    def test_train_g2p_pronounce(self):
        """Call async_test_g2p_pronounce."""
        _LOOP.run_until_complete(self.async_test_g2p_pronounce())

    # -------------------------------------------------------------------------

    async def async_test_g2p_error(self):
        """Check pronunciation error."""
        num_guesses = 2
        fake_words = ["foo", "bar"]

        def fake_guess(words, *args, num_guesses=0, **kwargs):
            """Fail with an exception."""
            raise FakeException()

        with patch("rhasspynlu.g2p.guess_pronunciations", new=fake_guess):
            g2p_id = str(uuid.uuid4())
            pronounce = G2pPronounce(
                id=g2p_id,
                words=fake_words,
                siteId=self.siteId,
                sessionId=self.sessionId,
            )

            # Send in request
            result = None
            async for response in self.hermes.on_message(pronounce):
                result = response

        self.assertIsInstance(result, G2pError)
        self.assertEqual(result.id, g2p_id)
        self.assertEqual(result.siteId, self.siteId)
        self.assertEqual(result.sessionId, self.sessionId)

    def test_train_g2p_error(self):
        """Call async_test_g2p_error."""
        _LOOP.run_until_complete(self.async_test_g2p_error())
