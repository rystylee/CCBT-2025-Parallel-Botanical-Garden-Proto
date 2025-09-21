import argparse

from pythonosc import udp_client


def send_test_message(ip, port, address, message):
    client = udp_client.SimpleUDPClient(ip, port)
    client.send_message(address, message)
    print(f"Sent to {address}: {message}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--address", default="/process")
    parser.add_argument("--message", default="こんにちは")
    args = parser.parse_args()
    
    send_test_message(args.ip, args.port, args.address, args.message)
