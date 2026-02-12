# !/bin/bash

curl -L --fail --retry 5 --retry-delay 5 -C - -o lib-llm_1.7-m5stack1_arm64.deb "https://www.dropbox.com/scl/fi/pn1sqz2h82t765vg86xji/lib-llm_1.7-m5stack1_arm64.deb?rlkey=fj541gcqffuvkgse0vquaqkk5&st=6ig5cy98&dl=1"
curl -L --fail --retry 5 --retry-delay 5 -C - -o llm-llm_1.8-m5stack1_arm64.deb "https://www.dropbox.com/scl/fi/ckhsr0cupj0d2cwe5teim/llm-llm_1.8-m5stack1_arm64.deb?rlkey=e3jb5d1m5goag2jrggqj6hcig&st=0rb4706j&dl=1"
curl -L --fail --retry 5 --retry-delay 5 -C - -o llm-melotts_1.7-m5stack1_arm64.deb "https://www.dropbox.com/scl/fi/d3gdkyiebu1ddahai9vh3/llm-melotts_1.7-m5stack1_arm64.deb?rlkey=4hpt06prm5ghy5dwu0eapz8c4&st=l0vnyw21&dl=0"

dpkg -i lib-llm_1.7-m5stack1_arm64.deb
dpkg -i llm-llm_1.8-m5stack1_arm64.deb
dpkg -i llm-melotts_1.7-m5stack1_arm64.deb