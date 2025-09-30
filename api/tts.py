import json
from loguru import logger

from stackflow.utils import create_tcp_connection, close_tcp_connection
from stackflow.utils import send_json, receive_response, parse_setup_response, exit_session
from api.utils import TTS_SETTINGS


class StackFlowTTSClient:
    def __init__(self, config: dict):
        self.config = config
        self.set_params(config)

        self.sock = create_tcp_connection("localhost", 10001)
        self._init()

    def __del__(self):
        reset_date = self._create_reset_data()
        send_json(self.sock, reset_date)
        response = receive_response(self.sock)
        logger.debug(f"reset response: {response}")

        close_tcp_connection(self.sock)

    def set_params(self, config: dict):
        lang = config.get("common").get("lang")
        self.model = TTS_SETTINGS.get(lang).get("model")

        logger.info("[TTS info]")
        logger.info(f"lang: {lang}")
        logger.info(f"model: {self.model}")

    def speak(self, text: str) -> str:
        inference_date = self._create_inference_data(text)
        send_json(self.sock, inference_date)
        response = receive_response(self.sock, timeout=10.0)
        logger.debug(f"tts response: {response}")

        # reset_date = self._create_reset_data()
        # send_json(self.sock, reset_date)
        # response = receive_response(self.sock)
        # logger.debug(f"reset response: {response}")

    def _init(self):
        logger.info("Setup TTS...")

        audio_setup_data = self._create_audio_setup_data()
        sent_request_id = audio_setup_data["request_id"]
        send_json(self.sock, audio_setup_data)
        response = receive_response(self.sock)
        response_data = json.loads(response)
        self.audio_work_id = parse_setup_response(response_data, sent_request_id)
        logger.debug(f"audio setup response: {response_data}")

        tts_setup_data = self._create_tts_setup_data()
        sent_request_id = tts_setup_data["request_id"]
        send_json(self.sock, tts_setup_data)
        response = receive_response(self.sock)
        response_data = json.loads(response)
        self.tts_work_id = parse_setup_response(response_data, sent_request_id)
        logger.debug(f"tts setup response: {response}")
        logger.debug(f"tts_work_id: {self.tts_work_id}")

        logger.info("Setup TTS finished.")

    def _create_audio_setup_data(self) -> dict:
        return {
            "request_id": "audio_setup",
            "work_id": "audio",
            "action": "setup",
            "object": "audio.setup",
            "data": {
                "capcard": 0,
                "capdevice": 0,
                "capVolume": 0.5,
                "playcard": 0,
                "playdevice": 1,
                "playVolume": 0.15
            }
        }

    def _create_tts_setup_data(self) -> dict:
        return {
            "request_id": "melotts_setup",
            "work_id": "melotts",
            "action": "setup",
            "object": "melotts.setup",
            "data": {
                "model": self.model,
                "response_format": "sys.pcm",
                "input": ["tts.utf-8.stream"],
                "enoutput": False,
                "enaudio": True
            }
        }

    def _create_inference_data(self, text: str) -> dict:
        return {
            "request_id": "tts_inference",
            "work_id": self.tts_work_id,
            "action": "inference",
            "object": "tts.utf-8.stream",
            "data": {
                "delta": text,
                "index": 0,
                "finish": True
            }
        }

    def _create_reset_data(self) -> dict:
        return {
            "request_id": "4",
            "work_id": "sys",
            "action": "reset"
        }
    