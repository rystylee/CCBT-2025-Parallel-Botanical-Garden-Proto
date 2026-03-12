# 事前録音音声ファイル

このディレクトリには、日本語以外のデバイスで再生する事前録音済みの音声ファイルを配置します。

## ファイル配置

`config/config.json`の`audio.prerecorded_audio.files`セクションで定義された言語別ファイルを配置してください。

デフォルト設定:
- `output_en.wav` - 英語デバイス用（Device ID末尾: 1）
- `output_fr.wav` - フランス語デバイス用（Device ID末尾: 3）
- `output_fa.wav` - ペルシャ語デバイス用（Device ID末尾: 5）
- `output_ar.wav` - アラビア語デバイス用（Device ID末尾: 7）

## 音声ファイル要件

- **フォーマット**: WAV形式推奨
- **サンプルレート**: 48000Hz（システム設定に合わせる）
- **チャンネル**: 2ch（ステレオ）
- **ビット深度**: 16bit（s16）

異なるフォーマットのファイルでも、FFmpegによる自動変換が有効な場合は再生可能です（`audio.enable_ffmpeg_convert: true`）。

## 動作

- **日本語デバイス**: TTS（Text-to-Speech）で動的に音声を生成して再生
- **日本語以外**: このディレクトリの事前録音ファイルを再生

音声ファイルが見つからない場合、警告ログが出力され、OUTPUT phaseはスキップされます。
