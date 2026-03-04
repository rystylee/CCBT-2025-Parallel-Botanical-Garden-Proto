#!/usr/bin/env python3
"""
オーディオデバイス診断スクリプト

実機到着時に実行して、RME Fireface UC (または代替IF) の
認識状況・チャンネル数・録音テストを行う。

Usage:
  python -m input_controller.check_audio
  python input_controller/check_audio.py
"""
import subprocess, sys, os, json


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
            print(f"  ERROR (rc={r.returncode}): {r.stderr.strip()[:200]}")
        return r.returncode == 0
    except FileNotFoundError:
        print(f"  NOT FOUND: {cmd[0]}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT")
        return False


def main():
    section("1. Kernel & ALSA Version")
    run(["uname", "-r"])
    run(["cat", "/proc/asound/version"])

    section("2. USB Audio Devices")
    run(["lsusb"])

    section("3. ALSA Sound Cards")
    run(["cat", "/proc/asound/cards"])

    section("4. ALSA PCM Devices (capture)")
    run(["arecord", "-l"])

    section("5. ALSA PCM Devices (playback)")
    run(["aplay", "-l"])

    section("6. PipeWire / PulseAudio Status")
    pw = run(["pw-cli", "info", "all"])
    if not pw:
        run(["pactl", "info"])

    section("7. PipeWire Sources (input devices)")
    pw = run(["pw-cli", "list-objects"])
    if not pw:
        run(["pactl", "list", "sources", "short"])

    section("8. sounddevice (Python)")
    try:
        import sounddevice as sd
        print(sd.query_devices())
        print(f"\nDefault input:  {sd.default.device[0]}")
        print(f"Default output: {sd.default.device[1]}")
    except ImportError:
        print("  sounddevice not installed: pip install sounddevice")
    except Exception as e:
        print(f"  Error: {e}")

    section("9. PyAudio (Python)")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            print(f"  [{i}] {info['name']:<40s} "
                  f"in={info['maxInputChannels']} "
                  f"out={info['maxOutputChannels']} "
                  f"sr={int(info['defaultSampleRate'])}")
        pa.terminate()
    except ImportError:
        print("  pyaudio not installed: pip install pyaudio")
    except Exception as e:
        print(f"  Error: {e}")

    section("10. Quick Record Test (2sec, default device)")
    test_wav = "/tmp/ccbt_audio_test.wav"
    print("  Attempting arecord 2sec on hw:0,0 ...")
    ok = run(["arecord", "-D", "hw:0,0", "-f", "S16_LE", "-r", "16000",
              "-c", "1", "-d", "2", test_wav])
    if ok and os.path.exists(test_wav):
        size = os.path.getsize(test_wav)
        print(f"  Recorded: {test_wav} ({size} bytes)")
        # try multichannel
        for ch in [2, 4, 8]:
            test_mc = f"/tmp/ccbt_audio_test_{ch}ch.wav"
            print(f"\n  Attempting {ch}ch record on hw:0,0 ...")
            ok_mc = run(["arecord", "-D", "hw:0,0", "-f", "S16_LE",
                         "-r", "16000", "-c", str(ch), "-d", "2", test_mc])
            if ok_mc and os.path.exists(test_mc):
                print(f"  ✓ {ch}ch recording OK ({os.path.getsize(test_mc)} bytes)")
            else:
                print(f"  ✗ {ch}ch recording FAILED")

    # Try all hw devices
    section("11. Multi-device Scan")
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
        lines = r.stdout.strip().split("\n")
        for line in lines:
            if line.startswith("card"):
                parts = line.split(":")
                card_num = parts[0].split()[-1]
                dev_part = [p for p in parts if "device" in p.lower()]
                if dev_part:
                    dev_num = dev_part[0].strip().split()[1].rstrip(",")
                    hw = f"hw:{card_num},{dev_num}"
                    print(f"  Testing {hw} ...")
                    test_f = f"/tmp/ccbt_test_{hw.replace(':','_').replace(',','_')}.wav"
                    run(["arecord", "-D", hw, "-f", "S16_LE", "-r", "16000",
                         "-c", "1", "-d", "1", test_f])
    except Exception as e:
        print(f"  Error: {e}")

    section("12. Summary")
    print("  上記の結果を確認して input_config.json を設定してください。")
    print("  特に以下を確認:")
    print("    - RME Fireface UC が認識されているか")
    print("    - 何チャンネル入力が使えるか (4ch必要)")
    print("    - どのバックエンドが使えるか (sounddevice / pyaudio / alsa_raw)")
    print("    - audio_device にどの値を指定すべきか")


if __name__ == "__main__":
    main()
