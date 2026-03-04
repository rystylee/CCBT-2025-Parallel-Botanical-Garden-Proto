"""
OSC送信 — 既存プロジェクトの /bi/input [text, soft_prefix_b64, relay_count] へ
"""
from loguru import logger
from pythonosc import udp_client, osc_message_builder


class BiInputSender:
    OSC_ADDRESS = "/bi/input"

    def send(self, host: str, port: int, text: str,
             soft_prefix_b64: str, relay_count: int = 0):
        try:
            c = udp_client.SimpleUDPClient(host, port)
            msg = osc_message_builder.OscMessageBuilder(address=self.OSC_ADDRESS)
            msg.add_arg(text)
            msg.add_arg(soft_prefix_b64)
            msg.add_arg(relay_count)
            c.send(msg.build())
            logger.debug(f"  → {host}:{port}")
        except Exception as e:
            logger.error(f"Send failed {host}:{port}: {e}")

    def send_to_targets(self, targets, text: str,
                        soft_prefix_b64: str, relay_count: int = 0):
        for t in targets:
            self.send(t.ip, t.port, text, soft_prefix_b64, relay_count)
