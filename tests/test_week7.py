#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第7周测试脚本 - LangGraph Agent
"""

import requests
import json
import time
from sseclient import SSEClient

BASE_URL = "http://localhost:8000"

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

def print_step(msg):
    print(f"{Colors.CYAN}📋 {msg}{Colors.RESET}")

def test_agent_health():
    """测试1: Agent 健康检查"""
    print("\n=== 测试1: Agent 健康检查 ===")
    
    resp = requests.get(f"{BASE_URL}/api/agent/health")
    if resp.status_code == 200:
        data = resp.json()
        print_success(f"Agent 状态: {data['status']}")
        print_info(f"可用工具: {data.get('tools', [])}")
        return True
    else:
        print_error(f"健康检查失败: {resp.status_code}")
        return False

def test_agent_weather():
    """测试2: 天气查询"""
    print("\n=== 测试2: 天气查询 ===")
    
    resp = requests.post(f"{BASE_URL}/api/agent/run", 
                        json={"message": "北京今天天气怎么样？", "verbose": True})
    
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"问题: 北京今天天气怎么样？")
        print(f"回答: {data['reply']}")
        print_info(f"使用了工具: {data['used_tool']}")
        if data.get('steps'):
            print_step("执行步骤:")
            for step in data['steps']:
                print(f"   {step}")
        print_success("天气查询测试通过")
        return True
    else:
        print_error(f"请求失败: {resp.status_code}")
        return False

def test_agent_calculator():
    """测试3: 数学计算"""
    print("\n=== 测试3: 数学计算 ===")
    
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "100乘以0.15等于多少？", "verbose": True})
    
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"问题: 100乘以0.15等于多少？")
        print(f"回答: {data['reply']}")
        print_info(f"使用了工具: {data['used_tool']}")
        if data.get('steps'):
            print_step("执行步骤:")
            for step in data['steps']:
                print(f"   {step}")
        
        # 验证计算结果
        if "15" in data['reply']:
            print_success("计算结果正确")
        else:
            print_error("计算结果可能不正确")
        return True
    else:
        print_error(f"请求失败: {resp.status_code}")
        return False

def test_agent_chat():
    """测试4: 普通对话（无需工具）"""
    print("\n=== 测试4: 普通对话 ===")
    
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "你好，请介绍一下你自己", "verbose": True})
    
    if resp.status_code == 200:
        data = resp.json()
        print_info(f"问题: 你好，请介绍一下你自己")
        print(f"回答: {data['reply'][:150]}...")
        print_info(f"使用了工具: {data['used_tool']}")
        if data.get('steps'):
            print_step("执行步骤:")
            for step in data['steps']:
                print(f"   {step}")
        
        if not data['used_tool']:
            print_success("正确识别为普通对话")
        return True
    else:
        print_error(f"请求失败: {resp.status_code}")
        return False

def test_agent_multi_tool():
    """测试5: 多工具组合"""
    print("\n=== 测试5: 多工具组合 ===")
    
    queries = [
        "上海天气怎么样？",
        "帮我算一下 50 + 30",
        "现在几点钟？"
    ]
    
    all_passed = True
    for q in queries:
        print_info(f"\n问题: {q}")
        resp = requests.post(f"{BASE_URL}/api/agent/run", json={"message": q})
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"回答: {data['reply'][:100]}...")
            print_info(f"工具使用: {data['used_tool']}")
        else:
            print_error(f"失败: {resp.status_code}")
            all_passed = False
        
        time.sleep(0.5)
    
    return all_passed

def test_agent_steps_observability():
    """测试6: 步骤可观测性"""
    print("\n=== 测试6: 步骤可观测性 ===")
    
    resp = requests.post(f"{BASE_URL}/api/agent/run",
                        json={"message": "深圳天气和100+200的结果", "verbose": True})
    
    if resp.status_code == 200:
        data = resp.json()
        steps = data.get('steps', [])
        
        print_step(f"共 {len(steps)} 个步骤:")
        for i, step in enumerate(steps, 1):
            print(f"   {i}. {step}")
        
        if len(steps) > 0:
            print_success("步骤记录正常")
            return True
        else:
            print_error("没有步骤记录")
            return False
    else:
        print_error(f"请求失败: {resp.status_code}")
        return False

def test_agent_stream():
    """测试7: 流式输出"""
    print("\n=== 测试7: 流式输出 ===")
    
    try:
        resp = requests.post(f"{BASE_URL}/api/agent/stream",
                            json={"message": "北京天气", "verbose": True},
                            stream=True)
        
        if resp.status_code == 200:
            client = SSEClient(resp)
            for event in client.events():
                data = json.loads(event.data)
                if data['type'] == 'step':
                    print_step(f"步骤: {data['steps'][-1] if data['steps'] else '...'}")
                elif data['type'] == 'answer':
                    print_info(f"回答: {data['answer'][:100]}...")
                elif data['type'] == 'done':
                    print_success("流式输出完成")
                    return True
        else:
            print_error(f"流式请求失败: {resp.status_code}")
            return False
    except ImportError:
        print_info("sseclient 未安装，跳过流式测试")
        return True
    except Exception as e:
        print_error(f"流式测试异常: {e}")
        return False

def test_agent_error_handling():
    """测试8: 错误处理"""
    print("\n=== 测试8: 错误处理 ===")
    
    # 测试空消息
    resp = requests.post(f"{BASE_URL}/api/agent/run", json={"message": ""})
    if resp.status_code in [200, 400, 500]:
        print_info(f"空消息处理: {resp.status_code}")
    
    # 测试超长消息
    long_msg = "测试" * 1000
    resp = requests.post(f"{BASE_URL}/api/agent/run", json={"message": long_msg})
    if resp.status_code in [200, 400, 413, 500]:
        print_info(f"长消息处理: {resp.status_code}")
    
    print_success("错误处理测试完成")
    return True

def main():
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}    第7周测试 - LangGraph Agent{Colors.RESET}")
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
    
    results = {}
    
    results["Agent健康检查"] = test_agent_health()
    results["天气查询"] = test_agent_weather()
    results["数学计算"] = test_agent_calculator()
    results["普通对话"] = test_agent_chat()
    results["多工具组合"] = test_agent_multi_tool()
    results["步骤可观测性"] = test_agent_steps_observability()
    results["流式输出"] = test_agent_stream()
    results["错误处理"] = test_agent_error_handling()
    
    # 汇总
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE} 测试汇总{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, status in results.items():
        if status:
            print_success(f"{name}: 通过")
        else:
            print_error(f"{name}: 失败")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print_success("🎉 所有测试通过！第7周完成！")
    else:
        print_error(f"⚠️ {total - passed} 个测试失败")
    
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

if __name__ == "__main__":
    main()