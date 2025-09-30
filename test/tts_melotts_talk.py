import argparse
import json
import os
import socket
import time
from pathlib import Path

def send_json_request(sock, request_data):
    """JSONリクエストをサーバーに送信"""
    try:
        # json_string = json.dumps(request_data)
        json_string = json.dumps(request_data, ensure_ascii=False) + "\n"
        sock.sendall(json_string.encode('utf-8'))
        print(f'送信したリクエスト: {json_string}')
        time.sleep(1)
    except Exception as e:
        print(f'リクエスト送信エラー: {e}')

# def receive_response(sock):
#     """サーバーからのレスポンスを受信して処理"""
#     try:
#         data = sock.recv(4096)
#         if data:
#             response = data.decode('utf-8')
#             print(f'受信したレスポンス: {response}')
#             return json.loads(response)
#     except Exception as e:
#         print(f'レスポンス受信エラー: {e}')
#     return None

def receive_response(sock):
    try:
        sock.settimeout(5.0)

        response = ''
        while True:
            part = sock.recv(4096).decode('utf-8')
            response += part
            if '\n' in response:
                break
        print(f'受信したレスポンス: {response.strip()}')
        return response.strip()
    except Exception as e:
        print(f"Error at receive_response: {e}")

def receive_json_line(sock, timeout=5.0):
    try:
        sock.settimeout(timeout)
        f = getattr(sock, "_rfile", None) or sock.makefile("rb")
        sock._rfile = f
        line = f.readline()
        if not line:
            raise RuntimeError("connection closed")
        response = json.loads(line.decode("utf-8").strip())
        print(f'受信したレスポンス: {response}')
        return response
    except Exception as e:
        print(f'レスポンス受信エラー: {e}')
    return None

def main(args):
    os.chdir(Path(__file__).parent)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    host, port, model, text = args.host, args.port, args.model, args.text

    try:
        client_socket.connect((host, port))
        print(f'サーバー {host}:{port} に接続しました')

        # # オーディオセットアップ
        # audio_setup = {
        #     "request_id": "audio_setup",
        #     "work_id": "audio",
        #     "action": "setup",
        #     "object": "audio.setup",
        #     "data": {
        #         "capcard": 0,
        #         "capdevice": 0,
        #         "capVolume": 0.5,
        #         "playcard": 0,
        #         "playdevice": 1,
        #         "playVolume": 0.15
        #     }
        # }
        # send_json_request(client_socket, audio_setup)
        # receive_response(client_socket)

        # # TTSセットアップ
        # tts_setup = {
        #     "request_id": "melotts_setup",
        #     "work_id": "melotts",
        #     "action": "setup",
        #     "object": "melotts.setup",
        #     "data": {
        #         "model": model,
        #         "response_format": "sys.pcm",
        #         "input": ["tts.utf-8.stream"],
        #         "enoutput": False,
        #         "enaudio": True
        #     }
        # }
        # send_json_request(client_socket, tts_setup)
        # receive_response(client_socket)

        # # TTS推論
        # inference_request = {
        #     "request_id": "tts_inference",
        #     "work_id": "melotts.1001",
        #     "action": "inference",
        #     "object": "tts.utf-8.stream",
        #     # "data": {
        #     #     "delta": text,
        #     #     "index": 0,
        #     #     "finish": True
        #     # }
        #     "data": text
        # }
        # send_json_request(client_socket, inference_request)
        # receive_response(client_socket)
        
        # time.sleep(5)
        
        # # リセット
        # reset_request = {
        #     "request_id": "4",
        #     "work_id": "sys",
        #     "action": "reset"
        # }
        # send_json_request(client_socket, reset_request)
        # receive_response(client_socket)

        # オーディオセットアップ
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
                "playVolume": 0.15
            }
        }
        send_json_request(client_socket, audio_setup)
        receive_response(client_socket)

        # TTSセットアップ
        tts_setup = {
            "request_id": "melotts_setup",
            "work_id": "melotts",
            "action": "setup",
            "object": "melotts.setup",
            "data": {
                "model": model,
                "response_format": "sys.pcm",
                "input": "tts.utf-8",
                "enoutput": False,
                "enaudio": True
            }
        }
        send_json_request(client_socket, tts_setup)
        response = receive_response(client_socket)
        tts_id = json.loads(response)["work_id"]

        # TTS推論
        inference_request = {
            "request_id": "tts_inference",
            "work_id": tts_id,
            "action": "inference",
            "object": "tts.utf-8",
            "data": text
        }
        send_json_request(client_socket, inference_request)
        response = receive_response(client_socket)
        # response = receive_json_line(client_socket)
        
        time.sleep(5)
        
        # リセット
        reset_request = {
            "request_id": "4",
            "work_id": "sys",
            "action": "reset"
        }
        send_json_request(client_socket, reset_request)
        receive_response(client_socket)

    except Exception as e:
        print(f'エラー: {e}')
    finally:
        client_socket.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TCP Client to send JSON data.')
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=10001)
    parser.add_argument("--model", type=str, default="melotts-ja-jp")
    parser.add_argument("--text", type=str, default="宙に舞う無数の星空。")
    args = parser.parse_args()
    main(args)
