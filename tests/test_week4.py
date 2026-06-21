import requests
import json
import time
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

BASE_URL = "http://localhost:8000"
TEST_DATA = os.path.join(os.path.dirname(__file__), "data")

def print_section(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

def test_health():
    print_section("测试1: 健康检查")
    resp = requests.get(f"{BASE_URL}/api/health")
    print(f"状态码: {resp.status_code}")
    print(f"响应: {resp.json()}")

def test_upload_pdf():
    print_section("测试2: 上传PDF")
    
    pdf_file = os.path.join(TEST_DATA, "test.pdf")
    if not os.path.exists(pdf_file):
        print("创建测试PDF文件...")
        c = canvas.Canvas(pdf_file, pagesize=letter)
        c.drawString(100, 750, "Docker入门指南")
        c.drawString(100, 730, "Docker是一个开源的应用容器引擎")
        c.drawString(100, 710, "Docker容器使用沙箱机制")
        c.save()
    
    with open(pdf_file, "rb") as f:
        files = {"file": ("test.pdf", f, "application/pdf")}
        resp = requests.post(f"{BASE_URL}/api/rag/upload", files=files)
    
    print(f"状态码: {resp.status_code}")
    if resp.status_code == 200:
        result = resp.json()
        print(f"文件: {result['file']}")
        print(f"文档块数: {result['chunks']}")
        print(f"任务ID: {result['task_id']}")
    else:
        print(f"错误: {resp.text}")

def test_search():
    print_section("测试3: 搜索知识库")
    
    queries = ["Docker", "容器", "虚拟化"]
    for q in queries:
        resp = requests.get(f"{BASE_URL}/api/rag/search", params={"q": q, "top_k": 2})
        if resp.status_code == 200:
            data = resp.json()
            print(f"\n搜索: {q}")
            for r in data['results']:
                print(f"  - 相关度: {r['score']:.3f} ({r['relevance']})")
                print(f"    内容: {r['text'][:80]}...")
        else:
            print(f"搜索失败: {resp.text}")

def test_rag_ask():
    print_section("测试4: RAG问答")
    
    questions = [
        "什么是Docker？",
        "Docker容器有什么特点？",
        "Python是什么？"  # 知识库里可能没有
    ]
    
    for q in questions:
        print(f"\n问题: {q}")
        resp = requests.get(f"{BASE_URL}/api/rag/ask", params={"question": q})
        if resp.status_code == 200:
            data = resp.json()
            print(f"回答: {data['answer'][:200]}...")
            print(f"有上下文: {data['has_context']}")
            if data['sources']:
                print(f"来源数: {len(data['sources'])}")
        else:
            print(f"错误: {resp.text}")
        time.sleep(1)

def test_chat():
    print_section("测试5: 普通对话（工具调用）")
    
    messages = [
        "北京天气怎么样？",
        "帮我计算 100 * 0.15",
        "你好，介绍一下你自己"
    ]
    
    for msg in messages:
        print(f"\n用户: {msg}")
        resp = requests.post(f"{BASE_URL}/api/chat", json={"message": msg})
        if resp.status_code == 200:
            data = resp.json()
            print(f"AI: {data['reply'][:150]}...")
            print(f"会话ID: {data['session_id'][:8]}...")
        else:
            print(f"错误: {resp.text}")
        time.sleep(1)

def test_stats():
    print_section("测试6: 系统统计")
    resp = requests.get(f"{BASE_URL}/api/stats")
    if resp.status_code == 200:
        data = resp.json()
        print(f"知识库文档数: {data['knowledge_base']['document_count']}")
        print(f"活跃会话数: {data['sessions']}")
        print(f"时间戳: {data['timestamp']}")
    else:
        print(f"获取统计失败: {resp.text}")

if __name__ == "__main__":
    print("开始测试第4周功能...\n")
    
    # 确保服务已启动
    try:
        test_health()
    except requests.exceptions.ConnectionError:
        print("错误: 服务未启动，请先运行 python run.py")
        exit(1)
    
    # 执行测试
    test_upload_pdf()
    time.sleep(2)
    test_search()
    time.sleep(2)
    test_rag_ask()
    time.sleep(2)
    test_chat()
    time.sleep(2)
    test_stats()
    
    print_section("测试完成")