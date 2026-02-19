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
apt install libsamplerate0 -y

# uv (python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# stackflow llm models
# apt install llm-model-llama3.2-1b-prefill-ax630c -y
# apt install llm-model-qwen2.5-1.5b-ax630c -y

# tiny swallow
curl -L --fail --retry 5 --retry-delay 5 -C - -o TinySwallow-1.5B-Instruct.zip "https://www.dropbox.com/scl/fi/fx3qsb556qj8uiyaww600/TinySwallow-1.5B-Instruct.zip?rlkey=v1lyxxb69yspjnj1h91w92nqb&st=mu54g261&dl=1"
unzip TinySwallow-1.5B-Instruct.zip
mv -i TinySwallow-1.5B-Instruct/m5stack/data/TinySwallow-1.5B /opt/m5stack/data/
mv -i TinySwallow-1.5B-Instruct/m5stack/data/models/mode_TinySwallow-1.5B.json /opt/m5stack/data/models/
mv -i TinySwallow-1.5B-Instruct/m5stack/scripts/TinySwallow-1.5B_tokenizer.py /opt/m5stack/scripts/

# melo tts
apt install llm-model-melotts-zh-cn -y
apt install llm-model-melotts-en-us -y
apt install llm-model-melotts-ja-jp -y

# openai
apt install llm-openai-api -y

# soft prefix
curl -L --fail --retry 5 --retry-delay 5 -C - -o lib-llm_1.7-m5stack1_arm64.deb "https://www.dropbox.com/scl/fi/pn1sqz2h82t765vg86xji/lib-llm_1.7-m5stack1_arm64.deb?rlkey=fj541gcqffuvkgse0vquaqkk5&st=6ig5cy98&dl=1"
curl -L --fail --retry 5 --retry-delay 5 -C - -o llm-llm_1.8-m5stack1_arm64.deb "https://www.dropbox.com/scl/fi/ckhsr0cupj0d2cwe5teim/llm-llm_1.8-m5stack1_arm64.deb?rlkey=e3jb5d1m5goag2jrggqj6hcig&st=0rb4706j&dl=1"
curl -L --fail --retry 5 --retry-delay 5 -C - -o llm-melotts_1.7-m5stack1_arm64.deb "https://www.dropbox.com/scl/fi/d3gdkyiebu1ddahai9vh3/llm-melotts_1.7-m5stack1_arm64.deb?rlkey=4hpt06prm5ghy5dwu0eapz8c4&st=l0vnyw21&dl=0"

dpkg -i lib-llm_1.7-m5stack1_arm64.deb
dpkg -i llm-llm_1.8-m5stack1_arm64.deb
dpkg -i llm-melotts_1.7-m5stack1_arm64.deb
