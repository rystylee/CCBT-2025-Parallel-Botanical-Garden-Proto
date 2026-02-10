#!/bin/bash

wget -qO /etc/apt/keyrings/StackFlow.gpg https://repo.llm.m5stack.com/m5stack-apt-repo/key/StackFlow.gpg
echo 'deb [arch=arm64 signed-by=/etc/apt/keyrings/StackFlow.gpg] https://repo.llm.m5stack.com/m5stack-apt-repo jammy ax630c' > /etc/apt/sources.list.d/StackFlow.list
apt update

# ubuntu package
apt install git -y
apt install curl -y
apt install unzip -y
apt install tmux -y
apt install ffmpeg -y
apt install i2c-tools -y

# uv (python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# stackflow llm models
apt install llm-model-llama3.2-1b-prefill-ax630c -y
apt install llm-model-qwen2.5-1.5b-ax630c -y

# melo tts
apt install llm-model-melotts-zh-cn -y
apt install llm-model-melotts-en-us -y
apt install llm-model-melotts-ja-jp -y

# openai
apt install llm-openai-api -y
