#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第8周最终测试 - 完整系统验收
"""

import requests
import json
import time
import sys
import os

BASE_URL = "http://localhost:8000"
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

def print_info(msg):
    print(f"{Colors.YELLOW}ℹ️ {msg}{Colors.RESET}")

def print_section(title):
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE} {title}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

def test_health():
    print_section("测试1: 健康检查")
    resp = requests.get(f"{BASE_URL}/api/health")
    if resp.status_code == 200:
        print_success(f"服务正常")
        return True
    print_error("服务异常")
    return False

def test_agent_weather():
    print_section("测试2: Agent - 天气查询")
    resp = requests.post(f"{BASE_URL}/api/agent/run", 
                        json={"message": "北京天气怎么样？"})
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"意图: {data['intent']}")
        print_info(f"使用了工具: {data['used_tool']}")
        print(f"回答: {data['reply'][:100]}...")
        return True
    print_error(f"失败: {resp.status_code}")
    return False

def test_agent_calculator():
    print_section("测试3: Agent - 数学计算")
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "100 * 0.15"})
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"使用了工具: {data['used_tool']}")
        print(f"回答: {data['reply']}")
        return "15" in data['reply']
    return False

def test_agent_rag():
    print_section("测试4: Agent - RAG问答")
    upload_pdf = os.path.join(ROOT_DIR, "迅腾智能卡口系统.pdf")
    if not os.path.exists(upload_pdf):
        print_info("测试文件不存在，跳过")
        return True
    
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "根据文档，什么是智能卡口？"})
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"使用了RAG: {data['used_rag']}")
        print(f"回答: {data['reply'][:150]}...")
        return True
    return False

def test_session():
    print_section("测试5: 会话管理")
    
    # 创建会话
    resp = requests.post(f"{BASE_URL}/api/session/create")
    if resp.status_code != 200:
        return False
    session_id = resp.json()['session_id']
    print_info(f"会话ID: {session_id[:8]}...")
    
    # 多轮对话
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "我叫张三", "session_id": session_id})
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "我叫什么名字？", "session_id": session_id})
    
    if resp.status_code == 200:
        data = resp.json()
        if "张三" in data['reply']:
            print_success("多轮对话记忆正确")
            return True
    return False

def test_upload_pdf():
    print_section("测试6: PDF上传")
    
    upload_pdf = os.path.join(ROOT_DIR, "迅腾智能卡口系统.pdf")
    if not os.path.exists(upload_pdf):
        print_info("测试文件不存在，跳过")
        return True
    
    with open(upload_pdf, "rb") as f:
        files = {"file": ("test.pdf", f, "application/pdf")}
        resp = requests.post(f"{BASE_URL}/api/rag/upload", files=files)
    
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"任务ID: {data['task_id'][:8]}...")
        print_success("上传成功")
        return True
    return False

def test_stats():
    print_section("测试7: 系统统计")
    resp = requests.get(f"{BASE_URL}/api/stats")
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"知识库文档数: {data['knowledge_base']['document_count']}")
        print_info(f"会话数: {data['sessions']}")
        return True
    return False

def main():
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}    第8周最终验收 - 完整AI Agent系统{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    
    if not test_health():
        print_error("服务未启动")
        sys.exit(1)
    
    results = {
        "健康检查": test_health(),
        "天气查询": test_agent_weather(),
        "数学计算": test_agent_calculator(),
        "RAG问答": test_agent_rag(),
        "会话管理": test_session(),
        "PDF上传": test_upload_pdf(),
        "系统统计": test_stats(),
    }
    
    print_section("验收汇总")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, status in results.items():
        if status:
            print_success(f"{name}: 通过")
        else:
            print_error(f"{name}: 失败")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print_success("🎉 恭喜！第1阶段完成！")
        print_info("你现在拥有：")
        print_info("  📚 知识库系统 (PDF上传/检索/RAG)")
        print_info("  🔧 工具调用系统 (天气/计算/时间)")
        print_info("  💬 多轮对话系统 (会话管理/上下文)")
        print_info("  🤖 Agent框架 (LangGraph/意图识别)")
        print_info("  📊 任务管理系统 (异步处理)")
        print_info("  🐳 Docker一键部署")
    else:
        print_error(f"{total - passed} 个测试失败")

if __name__ == "__main__":
    main()