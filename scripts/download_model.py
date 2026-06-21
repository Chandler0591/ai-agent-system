from modelscope import snapshot_download

# 下载向量化模型
print("正在下载向量化模型: BAAI/bge-small-zh-v1.5")
embedding_dir = snapshot_download(
    model_id="BAAI/bge-small-zh-v1.5",
    cache_dir="./models"
)
print(f"向量化模型已下载: {embedding_dir}")

# 下载重排序模型
print("\n正在下载重排序模型: BAAI/bge-reranker-base")
reranker_dir = snapshot_download(
    model_id="BAAI/bge-reranker-base",
    cache_dir="./models"
)
print(f"重排序模型已下载: {reranker_dir}")

print("\n所有模型下载完成！")