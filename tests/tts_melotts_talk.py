import argparse
import json
import os
import socket
import time
from pathlib import Path

from loguru import logger


def send_json(sock, data):
    try:
        json_data = json.dumps(data, ensure_ascii=False) + "\n"
        sock.sendall(json_data.encode("utf-8"))
    except Exception as e:
        logger.error(f"Error at send_json: {e}")


def receive_response(sock, timeout=None):
    try:
        if timeout:
            sock.settimeout(timeout)

        # response = ''
        # while True:
        #     part = sock.recv(4096).decode('utf-8')
        #     response += part
        #     if '\n' in response:
        #         break
        # return response.strip()
        response = ""
        while True:
            data = sock.recv(4096)
            if data:
                part = data.decode("utf-8")
                response += part
                if "\n" in response:
                    break
        return response.strip()
    except Exception as e:
        logger.error(f"Error at receive_response: {e}")
        return None


# def receive_json_line(sock, timeout=5.0):
#     try:
#         sock.settimeout(timeout)
#         f = getattr(sock, "_rfile", None) or sock.makefile("rb")
#         sock._rfile = f
#         line = f.readline()
#         if not line:
#             raise RuntimeError("connection closed")
#         response = line.decode("utf-8").strip()
#         print(f'受信したレスポンス: {response}')
#         return response
#     except Exception as e:
#         print(f'レスポンス受信エラー: {e}')
#     return None


def receive_json_line(sock, timeout=5.0):
    try:
        sock.settimeout(timeout)
        # 改行(\n)までを生ソケットで読み集める
        buf = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed")
            buf.extend(chunk)
            if b"\n" in buf:
                break
        line = bytes(buf).split(b"\n", 1)[0]
        response = json.loads(line.decode("utf-8"))
        print(f"受信したレスポンス: {response}")
        return response
    except Exception as e:
        print(f"レスポンス受信エラー: {e}")
        return None


def main(args):
    os.chdir(Path(__file__).parent)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    host, port, model, text = args.host, args.port, args.model, args.text

    try:
        client_socket.connect((host, port))
        logger.info(f"Connected server {host}:{port}")

        logger.info("Setup TTS...")

        logger.info("Audio setup")
        audio_setup = {
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
                "playVolume": 0.15,
            },
        }
        send_json(client_socket, audio_setup)
        response = receive_response(client_socket)
        response_data = json.loads(response)
        logger.info(f"audio setup response: {response_data}")
        logger.info("Finished audio setup")

        logger.info("TTS setup")
        tts_setup = {
            "request_id": "melotts_setup",
            "work_id": "melotts",
            "action": "setup",
            "object": "melotts.setup",
            "data": {
                "model": model,
                "response_format": "sys.pcm",
                "input": "tts.utf-8",
                # "input": ["tts.utf-8.stream"],
                "enoutput": False,
                "enaudio": True,
            },
        }
        send_json(client_socket, tts_setup)
        response = receive_response(client_socket)
        response_data = json.loads(response)
        logger.info(f"tts setup response: {response_data}")
        tts_id = json.loads(response)["work_id"]
        logger.info("Finished tts setup")

        logger.info("TTS inference")
        inference_request = {
            "request_id": "tts_inference",
            "work_id": tts_id,
            "action": "inference",
            "object": "tts.utf-8",
            "data": text,
            # "object": "tts.utf-8.stream",
            # "data": {
            #     "delta": text,
            #     "index": 0,
            #     "finish": True
            # }
        }
        send_json(client_socket, inference_request)
        # response = receive_response(client_socket, 5.0)
        response = receive_json_line(client_socket, 5.0)
        response_data = json.loads(response)
        logger.info(f"tts inference response: {response_data}")
        logger.info("Finished tts inference")

        time.sleep(5)

        logger.info("Reseting...")
        reset_request = {"request_id": "4", "work_id": "sys", "action": "reset"}
        send_json(client_socket, reset_request)
        response = receive_response(client_socket)

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        client_socket.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TCP Client to send JSON data.")
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=10001)
    parser.add_argument("--model", type=str, default="melotts-ja-jp")
    parser.add_argument("--text", type=str, default="宙に舞う無数の星空。")
    args = parser.parse_args()
    main(args)
