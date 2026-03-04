#!/usr/bin/env python3
"""
オーディオデバイス診断スクリプト

実機到着時に実行して、RME Fireface UC (または代替IF) の
認識状況・チャンネル数・録音テストを行う。

Usage:
  python -m input_controller.check_audio
  python input_controller/check_audio.py
"""
import subprocess, sys, os, re


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def run(cmd, ok_msg="OK"):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            print(r.stdout.strip() if r.stdout.strip() else ok_msg)
        else:
            err = (r.stderr.strip() or r.stdout.strip())[:200]
            print(f"  ERROR (rc={r.returncode}): {err}")
        return r.returncode == 0, r.stdout
    except FileNotFoundError:
        print(f"  NOT FOUND: {cmd[0]}")
        return False, ""
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT")
        return False, ""


def try_record(hw_device, channels, duration=2, sr=16000):
    """録音テスト: 成功したらTrue + ファイルサイズ"""
    safe = hw_device.replace(":", "_").replace(",", "_")
    test_f = f"/tmp/ccbt_test_{safe}_{channels}ch.wav"
    cmd = ["arecord", "-D", hw_device, "-f", "S16_LE",
           "-r", str(sr), "-c", str(channels), "-d", str(duration),
           "-t", "wav", "-q", test_f]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=duration + 5)
        if r.returncode == 0 and os.path.exists(test_f):
            size = os.path.getsize(test_f)
            return True, size
        return False, 0
    except Exception:
        return False, 0


def parse_arecord_devices(output):
    """
    arecord -l の出力からデバイス一覧をパース
    日本語/英語ロケール両対応:
      "card 0: PCH ..." or "カード 0: PCH ..."
    """
    devices = []
    pattern = re.compile(
        r'(?:card|カード)\s+(\d+).*?(?:device|デバイス)\s+(\d+)',
        re.IGNORECASE
    )
    for line in output.split("\n"):
        m = pattern.search(line)
        if m:
            card, dev = m.group(1), m.group(2)
            devices.append((card, dev, line.strip()))
    return devices


def main():
    section("1. Kernel & ALSA Version")
    run(["uname", "-r"])
    run(["cat", "/proc/asound/version"])

    section("2. USB Audio Devices")
    run(["lsusb"])

    section("3. ALSA Sound Cards")
    run(["cat", "/proc/asound/cards"])

    section("4. ALSA PCM Devices (capture)")
    ok, capture_output = run(["arecord", "-l"])

    section("5. ALSA PCM Devices (playback)")
    run(["aplay", "-l"])

    section("6. PipeWire / PulseAudio Status")
    try:
        r = subprocess.run(["pw-cli", "info", "0"], capture_output=True,
                           text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                s = line.strip()
                if any(k in s for k in ["version", "name =",
                                         "default.clock.rate",
                                         "host-name", "user-name"]):
                    print(f"  {s}")
            print("  PipeWire: ✓ running")
        else:
            print("  PipeWire: not running")
            run(["pactl", "info"])
    except FileNotFoundError:
        print("  pw-cli not found")
        run(["pactl", "info"])
    except Exception:
        pass

    section("7. PipeWire Audio Sources")
    try:
        r = subprocess.run(["pactl", "list", "sources", "short"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            print(r.stdout.strip())
    except Exception:
        print("  (pactl not available)")

    section("8. Python Audio Libraries")
    print("  --- sounddevice ---")
    try:
        import sounddevice as sd
        print(sd.query_devices())
        print(f"\n  Default input:  {sd.default.device[0]}")
        print(f"  Default output: {sd.default.device[1]}")
    except ImportError:
        print("  ✗ NOT INSTALLED → pip install sounddevice")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    print("\n  --- pyaudio ---")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0 or info["maxOutputChannels"] > 0:
                print(f"  [{i}] {info['name']:<40s} "
                      f"in={info['maxInputChannels']} "
                      f"out={info['maxOutputChannels']} "
                      f"sr={int(info['defaultSampleRate'])}")
        pa.terminate()
    except ImportError:
        print("  ✗ NOT INSTALLED → pip install pyaudio")
    except Exception as e:
        print(f"  ✗ Error: {e}")

    section("9. Recording Test (per device, multi-channel)")
    devices = parse_arecord_devices(capture_output)
    if not devices:
        print("  No capture devices found")
        print("  (外部IFが未接続の可能性があります)")
    else:
        for card, dev, name in devices:
            hw = f"hw:{card},{dev}"
            print(f"\n  === {hw} : {name} ===")
            max_ok_ch = 0
            for ch in [1, 2, 4, 8, 18]:
                ok, size = try_record(hw, ch, duration=1)
                status = f"✓ OK ({size} bytes)" if ok else "✗ FAIL"
                print(f"    {ch:2d}ch: {status}")
                if ok:
                    max_ok_ch = ch
                else:
                    break
            if max_ok_ch > 0:
                print(f"    → 最大 {max_ok_ch}ch 録音可能")
            else:
                print(f"    → hw直接は録音不可、plughwを試します")

        # plughw fallback
        print("\n  --- plughw (ALSA format conversion) ---")
        for card, dev, name in devices:
            plughw = f"plughw:{card},{dev}"
            max_ok = 0
            for ch in [1, 2, 4]:
                ok, size = try_record(plughw, ch, duration=1)
                status = f"✓ ({size}B)" if ok else "✗"
                print(f"    {plughw} {ch}ch: {status}")
                if ok:
                    max_ok = ch
                else:
                    break
            if max_ok > 0:
                print(f"    → plughw最大 {max_ok}ch")

    section("10. Summary & Recommendations")
    print("  現在の状態:")

    # USB Audio
    has_usb_audio = False
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True)
        low = r.stdout.lower()
        for kw in ["rme", "fireface", "behringer", "focusrite",
                    "audio interface", "usb audio"]:
            if kw in low:
                has_usb_audio = True
    except Exception:
        pass

    if has_usb_audio:
        print("    ✓ USB Audio IF が接続されています")
    else:
        print("    ✗ USB Audio IF 未接続")
        print("      → RME Fireface UC 等を接続後に再実行")

    # Python libs
    libs = []
    try:
        import sounddevice; libs.append("sounddevice")
    except ImportError:
        pass
    try:
        import pyaudio; libs.append("pyaudio")
    except ImportError:
        pass

    if libs:
        print(f"    ✓ Python audio: {', '.join(libs)}")
    else:
        print("    ✗ Python audio library 未インストール")
        print("      → pip install sounddevice")

    print("\n  次のステップ:")
    print("    1. pip install sounddevice numpy soundfile \\")
    print("       faster-whisper python-osc loguru")
    print("    2. RME Fireface UC を USB 接続")
    print("    3. python -m input_controller.check_audio  (再実行)")
    print("    4. セクション9で最大チャンネル数を確認")
    print("    5. input_config.json を設定")
    print()
    print("  推奨 config 例 (Fireface UC が hw:1,0 で 8ch認識の場合):")
    print('    "audio_backend": "alsa_raw",')
    print('    "audio_device": "hw:1,0",')
    print('    "mic_channels": 4,')
    print()
    print("  PipeWire経由で動く場合:")
    print('    "audio_backend": "sounddevice",')
    print('    "audio_device": "",')


if __name__ == "__main__":
    main()
