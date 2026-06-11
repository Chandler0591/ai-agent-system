import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_upload_pdf():
    """测试PDF上传"""
    print("\n=== 测试1: 上传PDF ===")
    
    # 创建一个测试PDF（如果没有现成的）
    # 这里假设你有一个 test.pdf 文件
    
    files = {'file': ('test.pdf', open('test.pdf', 'rb'), 'application/pdf')}
    response = requests.post(f"{BASE_URL}/rag/upload", files=files)
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

def test_search():
    """测试搜索"""
    print("\n=== 测试2: 搜索知识库 ===")
    response = requests.get(f"{BASE_URL}/rag/search", params={"q": "Docker", "top_k": 2})
    print(f"状态码: {response.status_code}")
    results = response.json()
    print(f"搜索: {results['query']}")
    for r in results['results']:
        print(f"  - 相似度: {r['score']:.3f}")
        print(f"    内容: {r['text'][:100]}...")

def test_rag_ask():
    """测试RAG问答"""
    print("\n=== 测试3: RAG问答 ===")
    response = requests.post(
        f"{BASE_URL}/rag/ask",
        json={"question": "什么是Docker？", "use_search": True}
    )
    print(f"状态码: {response.status_code}")
    print(f"回答: {response.json()['answer']}")

def test_tool_calling():
    """测试工具调用（第2周功能）"""
    print("\n=== 测试4: 工具调用 ===")
    response = requests.post(
        f"{BASE_URL}/chat",
        json={"message": "北京天气怎么样？"}
    )
    print(f"状态码: {response.status_code}")
    print(f"回答: {response.json()['reply']}")

if __name__ == "__main__":
    print("开始测试第3周功能...")
    
    # 如果没有PDF文件，跳过上传测试
    try:
        test_upload_pdf()
    except FileNotFoundError:
        print("跳过PDF上传测试（需要先准备test.pdf文件）")
    
    time.sleep(1)
    test_search()
    time.sleep(1)
    test_rag_ask()
    time.sleep(1)
    test_tool_calling()