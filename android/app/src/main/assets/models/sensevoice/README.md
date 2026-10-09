# SenseVoice 模型

Debug 可将 sherpa-onnx 官方模型目录中的以下两个文件放到
`app/src/debug/assets/models/sensevoice/` 后重新构建 APK：

- `model.int8.onnx`
- `tokens.txt`

推荐模型：

`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`

下载地址和自动复制脚本见 `android/scripts/download-sensevoice-model.sh`。
Release 默认不把约 229 MB 权重打进 APK；首次录音结束后会下载官方固定版本到
应用私有目录。模型较大，不提交到 Git；下载失败时应用仍可以保存原始录音和手动文字。
