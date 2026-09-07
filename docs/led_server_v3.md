# LEDサーバー v3

`main.py` は `pca9685_osc_led_server_v3.start_led_server(config)` を呼び出します。更新したコードと `config/config.json` を配置し、通常どおりアプリケーションを再起動してください。別の設定ファイルを使用している場合は、下記のv3用設定をそのファイルにも追加してください。

## 設定

v2は従来の `led_control.pca9685` を、v3は専用の `led_control.pca9685_v3` を読み込みます。`led_control.enabled` とOSCポートを指定する `led_control.targets` は共通です。

`pca9685_v3` には、使用する機器に合わせて `pca9685` のI2Cアドレス・チャンネル・バス番号・PWM周波数・明るさ上限などをコピーし、以下を設定してください。同梱設定には追加済みです。

```json
"gamma": 2.2,
"led_timeout": 180.0,
"external_timeout": 180.0
```

v3は `pca9685` の値を引き継ぎません。`pca9685_v3` 内で省略した値にはv3の既定値が使用されます。

- 有効な `/led` が180秒途切れると、`bri` をフェードなしで0にします。
- `/bri_ex`・`/led/bri_ex`・`/led_ratio`・`/led/ratio` がすべて180秒途切れると、`led_ratio` を1.0に戻します。
- 両者の期限は独立しています。外部入力が継続している間は、その寄与分の点灯が続きます。両方が期限切れになると出力は0になります。
- ガンマ補正は2.2です。混合後の明るさ0.5に対するPWM比率は、上限1.0なら約0.218です。

単体起動する場合は `python3 pca9685_osc_led_server_v3.py --port 9000` を使用します。単体起動はJSON設定を読み込まないため、機器固有の設定は `--addr`・`--ch`・`--bus` などで指定してください。タイムアウトの既定値は両方180秒で、`--led-timeout`・`--external-timeout` により変更できます。

## v2へ戻す場合

`main.py` の読み込みを次に戻してアプリケーションを再起動してください。

```python
from pca9685_osc_led_server_v2 import start_led_server
```

v2本体と `led_control.pca9685` は変更前の状態を維持しています。同梱のv2設定はガンマ1.0で、今回追加した入力タイムアウトはありません。

## 検証

```sh
python -B -m unittest discover -s tests -p test_pca9685_osc_led_server.py -v
```

実機では未検証です。タイムアウトは制御ループが動作し、PCA9685へ書き込める状態で機能します。
