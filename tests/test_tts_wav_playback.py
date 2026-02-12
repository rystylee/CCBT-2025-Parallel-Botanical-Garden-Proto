"""
Test script for TTS WAV file generation and playback.

This script tests the new speak_to_file() method that:
1. Generates WAV file from text using OpenAI-compatible API
2. Optionally converts the WAV file with FFmpeg
3. Plays the WAV file using tinyplay command

Usage:
    python tests/test_tts_wav_playback.py
"""

import asyncio
import json
import sys
from pathlib import Path

from loguru import logger

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.tts import StackFlowTTSClient


async def test_wav_generation_and_playback():
    """Test WAV file generation and playback with StackFlowTTSClient"""
    logger.info("=== Starting TTS WAV Playback Test ===")

    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    # Test texts for different languages
    test_texts = {
        "ja": "こんにちは、今日はいい天気ですね。",
        "en": "Hello, it's a nice day today.",
        "zh": "你好，今天天气真好。",
    }

    lang = config.get("common", {}).get("lang", "ja")
    test_text = test_texts.get(lang, test_texts["ja"])

    logger.info(f"Testing with language: {lang}")
    logger.info(f"Test text: {test_text}")

    try:
        # Initialize TTS client
        logger.info("Initializing StackFlowTTSClient...")
        tts_client = StackFlowTTSClient(config)

        # Test speak_to_file method
        logger.info("Calling speak_to_file()...")
        await tts_client.speak_to_file(test_text)

        logger.info("✅ Test completed successfully!")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise


async def test_wav_generation_without_ffmpeg():
    """Test WAV file generation without FFmpeg conversion"""
    logger.info("=== Testing WAV Generation Without FFmpeg ===")

    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    # Disable FFmpeg conversion
    if "audio" not in config:
        config["audio"] = {}
    config["audio"]["enable_ffmpeg_convert"] = False

    test_text = "これはFFmpeg変換なしのテストです。"

    try:
        logger.info("Initializing TTS client (FFmpeg disabled)...")
        tts_client = StackFlowTTSClient(config)

        logger.info("Calling speak_to_file() without FFmpeg...")
        await tts_client.speak_to_file(test_text)

        logger.info("✅ Test without FFmpeg completed successfully!")

    except Exception as e:
        logger.error(f"❌ Test without FFmpeg failed: {e}")
        raise


async def test_wav_generation_with_rumble():
    """Test WAV file generation with rumble effect"""
    logger.info("=== Testing WAV Generation With Rumble Effect ===")

    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    # Enable rumble effect
    if "audio" not in config:
        config["audio"] = {}
    config["audio"]["enable_ffmpeg_convert"] = True
    config["audio"]["enable_rumble_effect"] = True

    test_text = "これはランブルエフェクト付きのテストです。"

    try:
        logger.info("Initializing TTS client (rumble enabled)...")
        tts_client = StackFlowTTSClient(config)

        logger.info("Calling speak_to_file() with rumble effect...")
        await tts_client.speak_to_file(test_text)

        logger.info("✅ Test with rumble effect completed successfully!")

    except Exception as e:
        logger.error(f"❌ Test with rumble effect failed: {e}")
        raise


async def main():
    """Run all tests"""
    logger.info("Starting TTS WAV playback tests...")

    # Test 1: Basic WAV generation and playback
    await test_wav_generation_and_playback()
    await asyncio.sleep(2)

    # Test 2: Without FFmpeg conversion
    await test_wav_generation_without_ffmpeg()
    await asyncio.sleep(2)

    # Test 3: With rumble effect
    await test_wav_generation_with_rumble()

    logger.info("=== All tests completed ===")


if __name__ == "__main__":
    asyncio.run(main())
