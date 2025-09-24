# !/bin/bash
# wget -c --tries=10 --timeout=30 --content-disposition "https://www.dropbox.com/scl/fi/fx3qsb556qj8uiyaww600/TinySwallow-1.5B-Instruct.zip?rlkey=v1lyxxb69yspjnj1h91w92nqb&st=mu54g261&dl=1"
# unzip unspecified

curl -L --fail --retry 5 --retry-delay 5 -C - -o TinySwallow-1.5B-Instruct.zip "https://www.dropbox.com/scl/fi/fx3qsb556qj8uiyaww600/TinySwallow-1.5B-Instruct.zip?rlkey=v1lyxxb69yspjnj1h91w92nqb&st=mu54g261&dl=1"

unzip TinySwallow-1.5B-Instruct.zip

mv -i TinySwallow-1.5B-Instruct/m5stack/data/TinySwallow-1.5B /opt/m5stack/data/
mv -i TinySwallow-1.5B-Instruct/m5stack/data/models/mode_TinySwallow-1.5B.json /opt/m5stack/data/models/
mv -i TinySwallow-1.5B-Instruct/m5stack/scripts/TinySwallow-1.5B_tokenizer.py /opt/m5stack/scripts/