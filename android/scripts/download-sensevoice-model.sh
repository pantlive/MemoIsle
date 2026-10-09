#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
asset_dir="$script_dir/../app/src/debug/assets/models/sensevoice"
model_url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
model_name="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
archive_path="${TMPDIR:-/tmp}/$model_name.tar.bz2"

mkdir -p "$asset_dir"
curl -fL --retry 3 -o "$archive_path" "${model_url}${model_name}.tar.bz2"
tar -xjf "$archive_path" -C "${TMPDIR:-/tmp}"
cp "${TMPDIR:-/tmp}/$model_name/model.int8.onnx" "$asset_dir/model.int8.onnx"
cp "${TMPDIR:-/tmp}/$model_name/tokens.txt" "$asset_dir/tokens.txt"
rm -f "$archive_path"
rm -rf "${TMPDIR:-/tmp}/$model_name"

echo "SenseVoice 模型已安装到 $asset_dir"
