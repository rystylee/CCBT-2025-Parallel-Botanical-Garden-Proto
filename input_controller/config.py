"""
入力コントローラ設定

自分 (10.0.0.200) から各BIデバイス (10.0.0.1~100) へ
マイクテキスト・センサーデータを送信するための設定。
"""
import json
from dataclasses import dataclass, field
from typing import List


@dataclass
class TargetDevice:
    device_id: int
    ip: str
    port: int = 8000


@dataclass
class MicChannelRule:
    """マイクチャンネルごとの送信ルール"""
    channel: int                           # 0-based
    targets: List[TargetDevice] = field(default_factory=list)
    min_text_len: int = 2                  # この文字数未満は送信しない


@dataclass
class SensorOscRule:
    """センサーOSC受信 → M5送信ルール"""
    osc_address: str                       # 受信OSCアドレス (例 "/sensor/moisture")
    targets: List[TargetDevice] = field(default_factory=list)
    data_key: str = ""


@dataclass
class InputControllerConfig:
    # --- ネットワーク ---
    self_ip: str = "10.0.0.200"
    osc_receive_port: int = 9001           # センサーOSC受信

    # --- オーディオバックエンド ---
    audio_backend: str = "sounddevice"     # "sounddevice" | "pyaudio" | "alsa_raw"
    audio_device: str = ""                 # "" = default / "hw:1,0" / デバイス名
    mic_channels: int = 4
    mic_sample_rate: int = 16000
    mic_record_sec: float = 8.0
    mic_interval_sec: float = 2.0
    mic_silence_threshold: float = 0.01

    # --- STT ---
    stt_model: str = "base"                # tiny/base/small/medium/large
    stt_language: str = "ja"
    stt_device: str = "cpu"                # "cpu" | "cuda"
    stt_max_workers: int = 4               # 並列STTワーカー数

    # --- スピーカー ---
    speaker_enabled: bool = True
    speaker_wav_dir: str = "./output_wav"
    speaker_player: str = "aplay"          # aplay / ffplay / mpv / paplay
    speaker_player_args: List[str] = field(default_factory=list)

    # --- soft prefix (bi/utils.py互換) ---
    soft_prefix_p: int = 1
    soft_prefix_h: int = 1536

    # --- ルーティング ---
    mic_rules: List[MicChannelRule] = field(default_factory=list)
    sensor_rules: List[SensorOscRule] = field(default_factory=list)


# ---------- ヘルパー ----------

def make_target(did: int, port: int = 8000) -> TargetDevice:
    return TargetDevice(device_id=did, ip=f"10.0.0.{did}", port=port)

def make_targets(ids, port: int = 8000) -> List[TargetDevice]:
    return [make_target(d, port) for d in ids]


def load_default_config() -> InputControllerConfig:
    """ch0→1-10, ch1→11-20, ch2→21-30, ch3→31-40, sensor→41-50"""
    return InputControllerConfig(
        mic_rules=[
            MicChannelRule(channel=0, targets=make_targets(range(1, 11))),
            MicChannelRule(channel=1, targets=make_targets(range(11, 21))),
            MicChannelRule(channel=2, targets=make_targets(range(21, 31))),
            MicChannelRule(channel=3, targets=make_targets(range(31, 41))),
        ],
        sensor_rules=[
            SensorOscRule(osc_address="/sensor/plant",
                          targets=make_targets(range(41, 51)),
                          data_key="plant"),
        ],
    )


def load_config_from_json(path: str) -> InputControllerConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    ic = data.get("input_controller", {})

    mic_rules = [
        MicChannelRule(channel=m["channel"],
                       targets=make_targets(m["target_ids"], m.get("port", 8000)),
                       min_text_len=m.get("min_text_len", 2))
        for m in ic.get("mic_rules", [])
    ]
    sensor_rules = [
        SensorOscRule(osc_address=s["osc_address"],
                      targets=make_targets(s["target_ids"], s.get("port", 8000)),
                      data_key=s.get("data_key", s["osc_address"]))
        for s in ic.get("sensor_rules", [])
    ]
    return InputControllerConfig(
        self_ip            = ic.get("self_ip", "10.0.0.200"),
        osc_receive_port   = ic.get("osc_receive_port", 9001),
        audio_backend      = ic.get("audio_backend", "sounddevice"),
        audio_device       = ic.get("audio_device", ""),
        mic_channels       = ic.get("mic_channels", 4),
        mic_sample_rate    = ic.get("mic_sample_rate", 16000),
        mic_record_sec     = ic.get("mic_record_sec", 8.0),
        mic_interval_sec   = ic.get("mic_interval_sec", 2.0),
        mic_silence_threshold = ic.get("mic_silence_threshold", 0.01),
        stt_model          = ic.get("stt_model", "base"),
        stt_language       = ic.get("stt_language", "ja"),
        stt_device         = ic.get("stt_device", "cpu"),
        stt_max_workers    = ic.get("stt_max_workers", 4),
        speaker_enabled    = ic.get("speaker_enabled", True),
        speaker_wav_dir    = ic.get("speaker_wav_dir", "./output_wav"),
        speaker_player     = ic.get("speaker_player", "aplay"),
        speaker_player_args= ic.get("speaker_player_args", []),
        soft_prefix_p      = ic.get("soft_prefix_p", 1),
        soft_prefix_h      = ic.get("soft_prefix_h", 1536),
        mic_rules          = mic_rules,
        sensor_rules       = sensor_rules,
    )
