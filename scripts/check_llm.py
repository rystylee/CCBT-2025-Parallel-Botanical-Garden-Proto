#!/usr/bin/env python3
"""
LLMテキスト生成チェック - デバイス上で実行

StackFlow LLM (TCP:10001) に直接接続し、プロンプトを送信して
テキスト生成が正常に動作するか確認する。

前提:
    StackFlow LLM サービスが起動済み (systemctl status llm-llm)

使い方:
    uv run python scripts/check_llm.py
    uv run python scripts/check_llm.py --prompt "空は"
    uv run python scripts/check_llm.py --lang en --prompt "The sky is"
    uv run python scripts/check_llm.py --model qwen2.5-0.5B-prefill-20e
"""

import argparse
import json
import socket
import sys
import time

# 言語別のデフォルト設定
DEFAULT_SETTINGS = {
    "ja": {
        "model": "TinySwallow-1.5B",
        "system_prompt": "あなたは詩人です。常に短い詩を日本語で生成します。",
        "prompt": "静かな夜に",
    },
    "en": {
        "model": "qwen2.5-0.5B-prefill-20e",
        "system_prompt": "You are a poet. You always generate short poems.",
        "prompt": "In the quiet night",
    },
    "zh": {
        "model": "qwen2.5-0.5B-prefill-20e",
        "system_prompt": "你是诗人。你总是在用中文生成短诗。",
        "prompt": "在寂静的夜晚",
    },
}


def send_json(sock, data):
    json_data = json.dumps(data, ensure_ascii=False) + "\n"
    sock.sendall(json_data.encode("utf-8"))


def receive_response(sock, timeout=10.0):
    sock.settimeout(timeout)
    response = ""
    while True:
        part = sock.recv(4096).decode("utf-8")
        if not part:
            raise ConnectionError("Connection closed")
        response += part
        if "\n" in response:
            break
    return response.strip()


def check_llm(host: str, port: int, lang: str, model: str, prompt: str, max_tokens: int):
    """StackFlow LLMに接続してテキスト生成をテスト"""

    settings = DEFAULT_SETTINGS.get(lang, DEFAULT_SETTINGS["ja"])
    if model is None:
        model = settings["model"]
    if prompt is None:
        prompt = settings["prompt"]
    system_prompt = settings["system_prompt"]

    print(f"[LLM CHECK] Host: {host}:{port}")
    print(f"[LLM CHECK] Model: {model}")
    print(f"[LLM CHECK] Lang: {lang}")
    print(f"[LLM CHECK] Prompt: {prompt}")
    print(f"[LLM CHECK] Max tokens: {max_tokens}")
    print()

    sock = None

    # --- Step 1: TCP接続 ---
    print("[LLM CHECK] Step 1: StackFlow TCP接続...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        print(f"[OK] TCP接続成功 ({host}:{port})")
    except ConnectionRefusedError:
        print(f"[FAIL] TCP接続拒否 ({host}:{port})")
        print("       → StackFlow LLMサービスが起動しているか確認:")
        print("         systemctl status llm-llm")
        print("         systemctl restart llm-llm")
        return False
    except socket.timeout:
        print(f"[FAIL] TCP接続タイムアウト ({host}:{port})")
        return False
    except Exception as e:
        print(f"[FAIL] TCP接続エラー: {e}")
        return False

    # --- Step 2: LLMセットアップ ---
    print("[LLM CHECK] Step 2: LLMモデルセットアップ...")
    try:
        init_data = {
            "request_id": "llm_check",
            "work_id": "llm",
            "action": "setup",
            "object": "llm.setup",
            "data": {
                "model": model,
                "response_format": "llm.utf-8.stream",
                "input": "llm.utf-8.stream",
                "enoutput": True,
                "max_token_len": max_tokens,
                "prompt": system_prompt,
            },
        }
        send_json(sock, init_data)
        response = receive_response(sock, timeout=30.0)
        response_data = json.loads(response)

        error = response_data.get("error", {})
        if error and error.get("code") != 0:
            print(f"[FAIL] LLMセットアップエラー: code={error.get('code')}, msg={error.get('message')}")
            return False

        llm_work_id = response_data.get("work_id")
        if not llm_work_id:
            print(f"[FAIL] work_id が取得できません: {response_data}")
            return False

        print(f"[OK] LLMセットアップ完了 (work_id: {llm_work_id})")
    except socket.timeout:
        print("[FAIL] LLMセットアップ タイムアウト（モデルロードに時間がかかっている可能性）")
        return False
    except Exception as e:
        print(f"[FAIL] LLMセットアップエラー: {e}")
        return False

    # --- Step 3: テキスト生成 ---
    print(f'[LLM CHECK] Step 3: テキスト生成 ("{prompt}")...')
    try:
        inference_data = {
            "request_id": "llm_check",
            "work_id": llm_work_id,
            "action": "inference",
            "object": "llm.utf-8.stream",
            "data": {"delta": prompt, "index": 0, "finish": True},
        }
        send_json(sock, inference_data)

        output = ""
        token_count = 0
        start_time = time.time()

        while True:
            response = receive_response(sock, timeout=15.0)
            response_data = json.loads(response)

            error = response_data.get("error")
            if error and error.get("code") != 0:
                print(f"[FAIL] 推論エラー: code={error['code']}, msg={error.get('message')}")
                break

            data = response_data.get("data")
            if data is None:
                break

            delta = data.get("delta", "")
            finish = data.get("finish", False)
            output += delta
            token_count += 1

            if finish:
                break

        elapsed = time.time() - start_time

        if not output:
            print("[FAIL] テキスト生成結果が空です")
            return False

        print(f"[OK] テキスト生成完了 ({elapsed:.2f}秒, {token_count}チャンク)")
        print(f"     入力:  {prompt}")
        print(f"     出力:  {output}")
    except socket.timeout:
        print("[FAIL] テキスト生成タイムアウト")
        return False
    except Exception as e:
        print(f"[FAIL] テキスト生成エラー: {e}")
        return False

    # --- Step 4: クリーンアップ ---
    print("[LLM CHECK] Step 4: セッション終了...")
    try:
        exit_data = {"request_id": "llm_exit", "work_id": llm_work_id, "action": "exit"}
        send_json(sock, exit_data)
        receive_response(sock, timeout=5.0)
        print("[OK] セッション終了")
    except Exception:
        print("[WARN] セッション終了時にエラー（問題なし）")
    finally:
        sock.close()

    print()
    print("[OK] LLM テキスト生成チェック完了 ✓")
    return True


def main():
    parser = argparse.ArgumentParser(description="LLMテキスト生成チェック（デバイス上で実行）")
    parser.add_argument("--host", type=str, default="localhost", help="StackFlow host (default: localhost)")
    parser.add_argument("--port", type=int, default=10001, help="StackFlow port (default: 10001)")
    parser.add_argument("--lang", type=str, default="ja", choices=["ja", "en", "zh"], help="言語 (default: ja)")
    parser.add_argument("--model", type=str, default=None, help="LLMモデル名（省略時は言語に応じて自動選択）")
    parser.add_argument("--prompt", type=str, default=None, help="テストプロンプト（省略時はデフォルト）")
    parser.add_argument("--max-tokens", type=int, default=128, help="最大トークン数 (default: 128)")
    args = parser.parse_args()

    ok = check_llm(args.host, args.port, args.lang, args.model, args.prompt, args.max_tokens)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
