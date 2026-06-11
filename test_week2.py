import requests
import time

BASE = "http://localhost:8000"

def test(name, msg):
    print(f"\n{'='*50}")
    print(f"测试: {name}")
    print(f"用户: {msg}")
    start = time.time()
    resp = requests.post(f"{BASE}/chat", json={"message": msg})
    elapsed = time.time() - start
    if resp.status_code == 200:
        print(f"AI: {resp.json()['reply']}")
    else:
        print(f"错误: {resp.status_code}")
    print(f"耗时: {elapsed:.2f}s")
    return resp.status_code == 200

# 测试列表
tests = [
    ("天气查询", "北京天气怎么样？"),
    ("数学计算", "100乘以0.15等于多少？"),
    ("混合查询", "上海天气和25+36的结果"),
    ("普通对话", "你好，你叫什么名字？"),
    ("多轮对话", "刚才那个城市温度是多少？"),
]

passed = 0
for name, msg in tests:
    if test(name, msg):
        passed += 1
    time.sleep(1)

print(f"\n{'='*50}")
print(f"通过: {passed}/{len(tests)}")
