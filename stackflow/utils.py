import socket
import json


def create_tcp_connection(host: str, port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def close_tcp_connection(sock):
    if sock:
        sock.close()


def send_json(sock, data):
    json_data = json.dumps(data, ensure_ascii=False) + '\n'
    sock.sendall(json_data.encode('utf-8'))


def receive_response(sock):
    response = ''
    while True:
        part = sock.recv(4096).decode('utf-8')
        response += part
        if '\n' in response:
            break
    return response.strip()

def parse_setup_response(response_data: dict, sent_request_id: str) -> str:
    error = response_data.get('error')
    request_id = response_data.get('request_id')

    if request_id != sent_request_id:
        print(f"Request ID mismatch: sent {sent_request_id}, received {request_id}")
        return None

    if error and error.get('code') != 0:
        print(f"Error Code: {error['code']}, Message: {error['message']}")
        return None

    return response_data.get('work_id')


def setup(sock, init_data):
    sent_request_id = init_data['request_id']
    send_json(sock, init_data)
    response = receive_response(sock)
    response_data = json.loads(response)
    return parse_setup_response(response_data, sent_request_id)


def exit_session(sock, deinit_data):
    send_json(sock, deinit_data)
    response = receive_response(sock)
    response_data = json.loads(response)
    print("Exit Response:", response_data)