import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_hybrid_search():
    print("\n=== 测试基础混合检索 ===")
    response = requests.get(f"{BASE_URL}/rag/v2/search", params={"q": "Docker容器", "top_k": 3})
    if response.status_code != 200:
        print(f"接口错误: {response.status_code}")
        return
    
    data = response.json()
    print(f"检索结果数: {len(data['documents'])}")
    for doc in data['documents'][:2]:
        print(f"  - {doc.get('text', '')[:100]}...")

def test_rerank():
    print("\n=== 测试重排序 ===")
    # 使用 ask 接口，设置 use_hyde=False
    response = requests.get(
        f"{BASE_URL}/rag/v2/ask", 
        params={"question": "Docker有什么特点？", "use_hyde": False}
    )
    
    if response.status_code != 200:
        print(f"接口错误: {response.status_code}")
        return
    
    data = response.json()
    
    # 兼容两种返回格式
    if 'answer' in data:
        print(f"回答: {data['answer'][:200]}")
    elif 'documents' in data:
        print(f"检索结果数: {len(data['documents'])}")
        for doc in data['documents'][:2]:
            print(f"  - {doc.get('text', '')[:100]}...")
    else:
        print(f"未知格式: {data.keys()}")

def test_hyde():
    print("\n=== 测试HyDE ===")
    response = requests.get(f"{BASE_URL}/rag/v2/ask", 
                           params={"question": "容器化技术有哪些优势？", "use_hyde": True})
    if response.status_code == 200:
        data = response.json()
        print(f"方法: {data.get('method', 'unknown')}")
        print(f"回答: {data['answer'][:200]}")
        print(f"来自缓存: {data.get('from_cache', False)}")

def test_cache():
    print("\n=== 测试缓存 ===")
    
    # 第一次查询
    start = time.time()
    response1 = requests.get(f"{BASE_URL}/rag/v2/ask", 
                            params={"question": "Docker是什么？"})
    time1 = time.time() - start
    
    # 第二次查询（应该命中缓存）
    start = time.time()
    response2 = requests.get(f"{BASE_URL}/rag/v2/ask", 
                            params={"question": "Docker是什么？"})
    time2 = time.time() - start
    
    print(f"第一次查询: {time1:.2f}s")
    print(f"第二次查询: {time2:.2f}s")
    
    if response2.status_code == 200:
        data = response2.json()
        print(f"缓存命中: {data.get('from_cache', False)}")

def test_compare():
    print("\n=== 测试方法对比 ===")
    response = requests.get(f"{BASE_URL}/rag/compare", 
                           params={"question": "Docker容器"})
    if response.status_code == 200:
        data = response.json()
        print(f"问题: {data['question']}")
        for method, result in data['methods'].items():
            print(f"  {method}: {result}")

def test_evaluate():
    print("\n=== 测试评估 ===")
    response = requests.get(f"{BASE_URL}/rag/evaluate")
    if response.status_code == 200:
        data = response.json()
        print("评估指标:")
        for metric, value in data.items():
            print(f"  {metric}: {value:.4f}")

if __name__ == "__main__":
    print("开始测试第5周功能...")
    
    test_hybrid_search()
    test_rerank()
    test_hyde()
    test_cache()
    test_compare()
    test_evaluate()
    
    print("\n测试完成！")