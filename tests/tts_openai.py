import os
from pathlib import Path

from loguru import logger
from openai import OpenAI

client = OpenAI(api_key="sk-", base_url="http://127.0.0.1:8000/v1")

output_path = Path(__file__).parent / "speech-en.wav"
with client.audio.speech.with_streaming_response.create(
    model="melotts-ja-jp",
    # model="melotts-en-us",
    response_format="wav",
    voice="",
    input="今日はいい天気ですね。楽しみだな",
    # input="hello.",
) as response:
    response.stream_to_file(output_path)


# Verify the generated file
if os.path.exists(output_path):
    file_size = os.path.getsize(output_path)
    logger.debug(f"Generated file size: {file_size} bytes")

    # Read first few bytes to check file format
    with open(output_path, "rb") as f:
        header = f.read(16)
        logger.debug(f"File header (first 16 bytes): {header.hex()}")

        # Check if it's a valid WAV file (should start with "RIFF")
        if not header.startswith(b"RIFF"):
            logger.warning("Generated file does not have RIFF header - may not be a valid WAV file")
else:
    logger.error(f"Output file not created: {output_path}")

logger.info(f"WAV file generated: {output_path}")
