FROM python:3.12.3-slim-bookworm

WORKDIR /app

# ---- 国内镜像加速（境外服务器可删除此段） ----
ARG USE_MIRROR=true
RUN if [ "$USE_MIRROR" = "true" ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources; \
        pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple; \
    fi

# 安装系统依赖（含时区）
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    tzdata \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
# 先装 CPU 版 PyTorch（避免拉 nvidia 423MB CUDA 包）
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 复制启动脚本
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 创建数据目录
RUN mkdir -p /app/chroma_data /app/tmp

# 暴露端口
EXPOSE 8000

# 启动入口（自动检查/下载模型 → 启动应用）
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
