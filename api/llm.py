import json
from loguru import logger

from stackflow.utils import create_tcp_connection, close_tcp_connection
from stackflow.utils import send_json, receive_response, parse_setup_response, exit_session
from api.utils import LLM_SETTINGS


class StackFlowLLMClient:
    def __init__(self, config: dict):
        self.config = config
        self.set_params(config)

        self.sock = create_tcp_connection("localhost", 10001)
        self.llm_work_id = self._init()

    def __del__(self):
        deinit_data = self._create_deinit_data()
        exit_session(self.sock, deinit_data)
        close_tcp_connection(self.sock)

    def set_params(self, config: dict):
        lang = config.get("stack_flow_llm").get("lang")

        self.model = LLM_SETTINGS.get(lang).get("model")
        self.max_tokens = config.get("stack_flow_llm").get("max_tokens")
        self.system_prompt = LLM_SETTINGS.get(lang).get("system_prompt")
        self.instruction_prompt = LLM_SETTINGS.get(lang).get("instruction_prompt")
        logger.info("[LLM info]")
        logger.info(f"lang: {lang}")
        logger.info(f"model: {self.model}")
        logger.info(f"max_tokens: {self.max_tokens}")
        logger.info(f"system_prompt: {self.system_prompt}")
        logger.info(f"instruction_prompt: {self.instruction_prompt}")
        logger.info("")

    def generate_text(self, query: str) -> str:
        prompt = self.instruction_prompt + query
        logger.info(f"prompt: {prompt}")

        send_data = self._create_send_data(prompt)
        send_json(self.sock, send_data)

        output  = ""
        while True:
            response = receive_response(self.sock)
            response_data = json.loads(response)

            data = self._parse_inference_response(response_data)
            if data is None:
                break

            delta = data.get('delta')
            finish = data.get('finish')
            output += delta
            logger.debug(delta)

            if finish:
                break

        return output

    def _init(self) -> str:
        logger.info("Setup LLM...")
        init_data = self._create_init_data()
        llm_work_id = self._setup(self.sock, init_data)
        logger.debug(f"llm_work_id: {llm_work_id}")
        logger.info("Setup LLM finished.")
        return llm_work_id

    def _setup(self, sock, init_data) -> str:
        sent_request_id = init_data['request_id']
        send_json(sock, init_data)
        response = receive_response(sock)
        response_data = json.loads(response)
        logger.debug(f"llm response: {response_data}")
        return parse_setup_response(response_data, sent_request_id)

    def _parse_inference_response(self, response_data: dict) -> str:
        error = response_data.get('error')
        if error and error.get('code') != 0:
            print(f"Error Code: {error['code']}, Message: {error['message']}")
            return None

        return response_data.get('data')

    def _create_init_data(self) -> dict:
        return {
            "request_id": "llm_001",
            "work_id": "llm",
            "action": "setup",
            "object": "llm.setup",
            "data": {
                "model": self.model,
                "response_format": "llm.utf-8.stream",
                "input": "llm.utf-8.stream",
                "enoutput": True,
                "max_token_len": self.max_tokens,
                "prompt": self.system_prompt
            }
        }

    def _create_deinit_data(self) -> dict:
        return {
            "request_id": "llm_exit",
            "work_id": self.llm_work_id,
            "action": "exit"
        }
    
    def _create_send_data(self, prompt: str) -> dict:
        return {
            "request_id": "llm_001",
            "work_id": self.llm_work_id,
            "action": "inference",
            "object": "llm.utf-8.stream",
            "data": {
                "delta": prompt,
                "index": 0,
                "finish": True
            }
        }
