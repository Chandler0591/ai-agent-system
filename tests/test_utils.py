import tempfile
import os

def test_pdf_handle():
    pdf_path = os.path.join(os.path.dirname(__file__), "data", "test.pdf")
    filename = os.path.basename(pdf_path)

    # 读取文件二进制内容
    with open(pdf_path, "rb") as f:
        content = f.read()

    # 创建临时文件并写入
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(content)
        tmp_path = tmp_file.name

    # 打印要求的三个变量
    print("=" * 50)
    print(f"临时文件路径 tmp_path: {tmp_path}")
    print(f"原文件名 filename: {filename}")
    print(f"文件字节大小 content 长度: {len(content)} bytes")
    # 如需查看部分二进制内容（避免刷屏）
    print(f"content 前50字节: {content[:50]}")
    print("=" * 50)

if __name__ == "__main__":
    print("测试python函数脚本...")
    test_pdf_handle()