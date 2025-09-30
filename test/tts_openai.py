from pathlib import Path
from openai import OpenAI

client = OpenAI(
    api_key="sk-",
    base_url="http://127.0.0.1:8000/v1"
)

speech_file_path = Path(__file__).parent / "speech-en.wav"
with client.audio.speech.with_streaming_response.create(
#   model="melotts-ja-jp",
  model="melotts-en-us",
  response_format="wav",
  voice="",
#   input="今日はいい天気ですね。"
  input="hello."
) as response:
  response.stream_to_file(speech_file_path)