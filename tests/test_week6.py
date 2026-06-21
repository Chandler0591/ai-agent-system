#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第6周测试脚本 - 对话系统
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

def print_info(msg):
    print(f"{Colors.YELLOW}ℹ️ {msg}{Colors.RESET}")

def test_create_session():
    """测试1: 创建会话"""
    print("\n=== 测试1: 创建会话 ===")
    
    resp = requests.post(f"{BASE_URL}/api/session/create")
    if resp.status_code == 200:
        data = resp.json()
        print_success(f"创建会话成功: {data['session_id'][:8]}...")
        return data['session_id']
    else:
        print_error(f"创建失败: {resp.status_code}")
        return None

def test_conversation(session_id):
    """测试2: 多轮对话"""
    print("\n=== 测试2: 多轮对话 ===")
    
    conversations = [
        "我叫张三，是一名软件工程师",
        "我刚才说我叫什么名字？",
        "我的职业是什么？",
        "帮我计算 100 + 200",
        "谢谢！"
    ]
    
    for msg in conversations:
        print(f"\n用户: {msg}")
        resp = requests.post(
            f"{BASE_URL}/api/conversation",
            json={"message": msg, "session_id": session_id}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"AI: {data['reply'][:150]}...")
            print_info(f"历史长度: {data['history_length']}")
        else:
            print_error(f"对话失败: {resp.status_code}")
            break
        
        time.sleep(0.5)

def test_context_understanding():
    """测试3: 上下文理解"""
    print("\n=== 测试3: 上下文理解 ===")
    
    # 创建新会话
    resp = requests.post(f"{BASE_URL}/api/session/create")
    session_id = resp.json()['session_id']
    
    # 第一轮
    print("\n用户: 我喜欢吃披萨")
    resp = requests.post(f"{BASE_URL}/api/conversation", 
                        json={"message": "我喜欢吃披萨", "session_id": session_id})
    print(f"AI: {resp.json()['reply'][:100]}...")
    
    # 第二轮（测试记忆）
    print("\n用户: 我刚才说了我喜欢吃什么？")
    resp = requests.post(f"{BASE_URL}/api/conversation", 
                        json={"message": "我刚才说了我喜欢吃什么？", "session_id": session_id})
    
    if resp.status_code == 200:
        reply = resp.json()['reply']
        if "披萨" in reply:
            print_success("上下文理解正确！")
        else:
            print_error(f"上下文理解失败: {reply[:100]}")
    else:
        print_error(f"请求失败: {resp.status_code}")

def test_multi_session():
    """测试4: 多会话隔离"""
    print("\n=== 测试4: 多会话隔离 ===")
    
    # 创建两个会话
    resp1 = requests.post(f"{BASE_URL}/api/session/create")
    resp2 = requests.post(f"{BASE_URL}/api/session/create")
    session1 = resp1.json()['session_id']
    session2 = resp2.json()['session_id']
    
    # 会话1 说
    requests.post(f"{BASE_URL}/api/conversation", 
                 json={"message": "我叫小明", "session_id": session1})
    
    # 会话2 说
    requests.post(f"{BASE_URL}/api/conversation", 
                 json={"message": "我叫小红", "session_id": session2})
    
    # 询问名字
    resp1 = requests.post(f"{BASE_URL}/api/conversation", 
                         json={"message": "我叫什么名字？", "session_id": session1})
    resp2 = requests.post(f"{BASE_URL}/api/conversation", 
                         json={"message": "我叫什么名字？", "session_id": session2})
    
    if resp1.status_code == 200 and resp2.status_code == 200:
        reply1 = resp1.json()['reply']
        reply2 = resp2.json()['reply']
        
        if "小明" in reply1 and "小红" in reply2:
            print_success("会话隔离正确！")
        else:
            print_error(f"会话隔离失败: {reply1[:50]} vs {reply2[:50]}")
    else:
        print_error("请求失败")

def test_session_list():
    """测试5: 会话列表"""
    print("\n=== 测试5: 会话列表 ===")
    
    resp = requests.get(f"{BASE_URL}/api/sessions")
    if resp.status_code == 200:
        data = resp.json()
        print_success(f"共 {data['count']} 个会话")
        for s in data['sessions'][:5]:
            print_info(f"  {s['session_id'][:8]}... - {s['message_count']}条消息")
    else:
        print_error(f"获取失败: {resp.status_code}")

def test_session_detail():
    """测试6: 会话详情"""
    print("\n=== 测试6: 会话详情 ===")
    
    # 先创建一个会话并聊天
    resp = requests.post(f"{BASE_URL}/api/session/create")
    session_id = resp.json()['session_id']
    
    requests.post(f"{BASE_URL}/api/conversation",
                 json={"message": "测试消息", "session_id": session_id})
    
    # 获取详情
    resp = requests.get(f"{BASE_URL}/api/session/{session_id}")
    if resp.status_code == 200:
        data = resp.json()
        print_success(f"会话详情: {data['message_count']}条消息")
        for msg in data['messages'][-3:]:
            print_info(f"  {msg['role']}: {msg['content'][:50]}...")
    else:
        print_error(f"获取失败: {resp.status_code}")

def test_delete_session():
    """测试7: 删除会话"""
    print("\n=== 测试7: 删除会话 ===")
    
    # 创建会话
    resp = requests.post(f"{BASE_URL}/api/session/create")
    session_id = resp.json()['session_id']
    
    # 删除
    resp = requests.delete(f"{BASE_URL}/api/session/{session_id}")
    if resp.status_code == 200:
        print_success("删除成功")
        
        # 验证已删除
        resp = requests.get(f"{BASE_URL}/api/session/{session_id}")
        if resp.status_code == 404:
            print_success("验证通过：会话已不存在")
        else:
            print_error("会话仍然存在")
    else:
        print_error(f"删除失败: {resp.status_code}")

def main():
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}    第6周测试 - 对话系统{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    
    # 检查服务
    try:
        resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
        if resp.status_code != 200:
            print_error("服务未启动")
            return
    except:
        print_error("服务未启动，请先运行: python run.py")
        return
    
    # 执行测试
    session_id = test_create_session()
    if session_id:
        test_conversation(session_id)
    
    test_context_understanding()
    test_multi_session()
    test_session_list()
    test_session_detail()
    test_delete_session()
    
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print_success("第6周测试完成！")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

if __name__ == "__main__":
    main()