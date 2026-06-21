#!/bin/bash
set -e

echo "========================================="
echo "  AI Agent System - Container Entrypoint"
echo "========================================="

MODEL_DIR="/app/models"
EMBEDDING_DIR="$MODEL_DIR/BAAI/bge-small-zh-v1.5"
RERANKER_DIR="$MODEL_DIR/BAAI/bge-reranker-base"

# ---- 模型自检 ----
check_model() {
    local dir=$1
    local name=$2
    if [ -d "$dir" ] && [ "$(ls -A "$dir" 2>/dev/null)" ]; then
        if [ -f "$dir/config.json" ] || [ -f "$dir/pytorch_model.bin" ] || [ -f "$dir/model.safetensors" ]; then
            echo "  [OK] $name"
            return 0
        fi
    fi
    echo "  [MISSING] $name"
    return 1
}

echo ""
echo "--- Checking local models ---"
MISSING=0
check_model "$EMBEDDING_DIR" "Embedding (bge-small-zh-v1.5)" || MISSING=1
check_model "$RERANKER_DIR" "Reranker  (bge-reranker-base)"   || MISSING=1

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo ">>> Downloading missing models via ModelScope ..."
    python -c "
from modelscope import snapshot_download
import sys, os

models = [
    ('BAAI/bge-small-zh-v1.5',  '$EMBEDDING_DIR'),
    ('BAAI/bge-reranker-base',   '$RERANKER_DIR'),
]

for model_id, target_dir in models:
    if os.path.isdir(target_dir):
        files = os.listdir(target_dir)
        has_model = any(f in files for f in ['config.json', 'pytorch_model.bin', 'model.safetensors'])
        if has_model:
            print(f'  [SKIP] {model_id} (already exists)')
            continue
    try:
        print(f'  [DOWNLOAD] {model_id} ...')
        snapshot_download(model_id=model_id, cache_dir='$MODEL_DIR')
        print(f'  [DONE] {model_id}')
    except Exception as e:
        print(f'  [FAIL] {model_id}: {e}', file=sys.stderr)
        print('  WARNING: Model download failed. RAG limited.')
" 2>&1
    echo ""
    echo ">>> Model download completed"
else
    echo "  All models present."
fi

echo ""
echo "--- Starting: $@ ---"
exec "$@"