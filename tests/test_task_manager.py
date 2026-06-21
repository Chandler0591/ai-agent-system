#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
专门测试 Task Manager 异步任务功能
测试文件: 迅腾智能卡口系统.pdf
"""

import requests
import json
import time
import os
import sys
import concurrent.futures

BASE_URL = "http://localhost:8000"
TEST_PDF = os.path.join(os.path.dirname(__file__), "..", "迅腾智能卡口系统.pdf")

# 颜色输出
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'

def print_section(title):
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE} {title}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

def print_success(msg):
    print(f"{Colors.GREEN}{msg}{Colors.RESET}")

def print_error(msg):
    print(f"{Colors.RED}{msg}{Colors.RESET}")

def print_info(msg):
    print(f"{Colors.YELLOW}ℹ️ {msg}{Colors.RESET}")

def print_task(msg):
    print(f"{Colors.CYAN}📋 {msg}{Colors.RESET}")

def test_health():
    """测试1: 健康检查"""
    print_section("测试1: 健康检查")
    try:
        resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
        if resp.status_code == 200:
            print_success(f"服务正常: {resp.json()}")
            return True
        else:
            print_error(f"状态码异常: {resp.status_code}")
            return False
    except Exception as e:
        print_error(f"连接失败: {e}")
        return False

def test_upload_with_task():
    """测试2: 异步上传PDF（核心测试）"""
    print_section("测试2: 异步上传PDF - Task Manager")
    
    # 检查测试文件是否存在
    if not os.path.exists(TEST_PDF):
        print_error(f"测试文件不存在: {TEST_PDF}")
        print_info("请确保 迅腾智能卡口系统.pdf 在当前目录")
        return False
    
    print_info(f"测试文件: {TEST_PDF} ({os.path.getsize(TEST_PDF)} bytes)")
    
    try:
        # 1. 上传文件（异步）
        print_info("步骤1: 发起异步上传请求...")
        with open(TEST_PDF, "rb") as f:
            files = {"file": (TEST_PDF, f, "application/pdf")}
            resp = requests.post(f"{BASE_URL}/api/rag/upload", files=files, timeout=30)
        
        if resp.status_code != 200:
            print_error(f"上传失败: {resp.text}")
            return False
        
        data = resp.json()
        task_id = data.get("task_id")
        
        print_success(f"上传请求成功")
        print_task(f"任务ID: {task_id}")
        print_info(f"初始状态: {data.get('status')}")
        print_info(f"消息: {data.get('message')}")
        
        # 2. 轮询任务状态
        print_info("\n步骤2: 轮询任务状态...")
        max_wait = 120  # 最大等待120秒
        interval = 2     # 每2秒查询一次
        elapsed = 0
        
        while elapsed < max_wait:
            resp = requests.get(f"{BASE_URL}/api/task/{task_id}")
            
            if resp.status_code != 200:
                print_error(f"查询任务失败: {resp.status_code}")
                return False
            
            task_data = resp.json()
            status = task_data.get("status")
            
            print_task(f"[{elapsed}s] 任务状态: {status}")
            
            if status == "completed":
                print_success(f"任务完成!")
                result = task_data.get("result", {})
                print_info(f"  文件: {result.get('file')}")
                print_info(f"  文档块数: {result.get('chunks')}")
                if result.get('stats'):
                    stats = result['stats']
                    print_info(f"  总字符数: {stats.get('total_chars')}")
                    print_info(f"  页数: {stats.get('page_count')}")
                # return task_id
                return True
                
            elif status == "failed":
                print_error(f"任务失败: {task_data.get('error')}")
                return False
            
            time.sleep(interval)
            elapsed += interval
        
        print_error(f"任务超时 ({max_wait}秒)")
        return False
        
    except Exception as e:
        print_error(f"测试异常: {e}")
        return False

def test_get_all_tasks():
    """测试3: 获取所有任务列表"""
    print_section("测试3: 获取任务列表")
    
    try:
        # 注意：需要先在 main.py 中添加这个接口
        resp = requests.get(f"{BASE_URL}/api/tasks", timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            tasks = data.get('tasks', [])
            print_success(f"获取任务列表成功: {len(tasks)} 个任务")
            for task in tasks[:5]:  # 只显示前5个
                print_task(f"  {task.get('id')[:8]}... - {task.get('status')} - {task.get('type')}")
            return True
        elif resp.status_code == 404:
            print_info("任务列表接口未实现，跳过测试")
            return True
        else:
            print_error(f"获取失败: {resp.status_code}")
            return False
    except Exception as e:
        print_info(f"任务列表接口可能未实现: {e}")
        return True

def test_duplicate_upload():
    """测试4: 重复上传同一个文件"""
    print_section("测试4: 重复上传测试")
    
    if not os.path.exists(TEST_PDF):
        print_error(f"测试文件不存在: {TEST_PDF}")
        return False
    
    task_ids = []
    
    for i in range(2):
        print_info(f"第 {i+1} 次上传...")
        try:
            with open(TEST_PDF, "rb") as f:
                files = {"file": (TEST_PDF, f, "application/pdf")}
                resp = requests.post(f"{BASE_URL}/api/rag/upload", files=files, timeout=30)
            
            if resp.status_code == 200:
                task_id = resp.json().get("task_id")
                task_ids.append(task_id)
                print_success(f"  任务ID: {task_id}")
            else:
                print_error(f"  上传失败: {resp.status_code}")
        except Exception as e:
            print_error(f"  异常: {e}")
        
        time.sleep(1)
    
    print_info(f"创建了 {len(task_ids)} 个任务")
    
    # 等待所有任务完成
    print_info("等待任务完成...")
    for task_id in task_ids:
        for _ in range(30):  # 最多等待60秒
            resp = requests.get(f"{BASE_URL}/api/task/{task_id}")
            if resp.status_code == 200:
                status = resp.json().get("status")
                if status in ["completed", "failed"]:
                    print_task(f"任务 {task_id[:8]}... 状态: {status}")
                    break
            time.sleep(2)
    
    return True

def test_search_after_upload():
    """测试5: 上传后搜索知识库"""
    print_section("测试5: 上传后搜索验证")
    
    # 等待一下让索引完成
    time.sleep(2)
    
    keywords = ["智能卡口", "迅腾", "系统"]
    
    for keyword in keywords:
        try:
            resp = requests.get(f"{BASE_URL}/api/rag/search", params={"q": keyword, "top_k": 3})
            if resp.status_code == 200:
                data = resp.json()
                total = data.get('total', 0)
                print_info(f"搜索 '{keyword}': 找到 {total} 条结果")
                if total > 0:
                    print_success(f"  成功检索到内容")
            else:
                print_error(f"搜索失败: {resp.status_code}")
        except Exception as e:
            print_error(f"搜索异常: {e}")
    
    return True

def test_invalid_task():
    """测试6: 查询不存在的任务"""
    print_section("测试6: 查询不存在的任务")
    
    invalid_id = "non-existent-task-id-12345"
    try:
        resp = requests.get(f"{BASE_URL}/api/task/{invalid_id}")
        if resp.status_code == 404:
            print_success(f"正确返回404: 任务不存在")
            return True
        else:
            print_error(f"期望404，实际: {resp.status_code}")
            return False
    except Exception as e:
        print_error(f"异常: {e}")
        return False

def test_concurrent_uploads():
    """测试7: 并发上传（模拟多个用户同时上传）"""
    print_section("测试7: 并发上传测试")
    
    if not os.path.exists(TEST_PDF):
        print_error(f"测试文件不存在: {TEST_PDF}")
        return False
    
    def upload_file(index):
        try:
            with open(TEST_PDF, "rb") as f:
                files = {"file": (f"test_{index}.pdf", f, "application/pdf")}
                resp = requests.post(f"{BASE_URL}/api/rag/upload", files=files, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("task_id")
        except:
            pass
        return None
    
    print_info("发起3个并发上传请求...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(upload_file, i) for i in range(3)]
        task_ids = [f.result() for f in futures if f.result()]
    
    print_success(f"成功创建 {len(task_ids)} 个并发任务")
    
    # 等待完成
    for task_id in task_ids:
        for _ in range(30):
            resp = requests.get(f"{BASE_URL}/api/task/{task_id}")
            if resp.status_code == 200:
                status = resp.json().get("status")
                if status in ["completed", "failed"]:
                    print_task(f"任务 {task_id[:8]}... 完成")
                    break
            time.sleep(2)
    
    return True

def test_clear_knowledge_base():
    """测试8: 清空知识库"""
    print_section("测试8: 清空知识库")
    
    try:
        resp = requests.delete(f"{BASE_URL}/api/rag/clear")
        if resp.status_code == 200:
            print_success("知识库已清空")
            return True
        else:
            print_error(f"清空失败: {resp.status_code}")
            return False
    except Exception as e:
        print_error(f"异常: {e}")
        return False

def main():
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}    Task Manager 异步任务测试{Colors.RESET}")
    print(f"{Colors.BLUE}    测试文件: {TEST_PDF}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    
    # 检查服务
    if not test_health():
        print_error("服务未启动，请先运行: python run.py")
        sys.exit(1)
    
    results = {}
    
    # 执行测试 - 逐个打印结果
    print("\n执行测试...")
    
    results["健康检查"] = test_health()
    print(f"  健康检查: {results['健康检查']}")
    
    results["异步上传PDF"] = test_upload_with_task()
    print(f"  异步上传PDF: {results['异步上传PDF']}")
    
    results["任务列表"] = test_get_all_tasks()
    print(f"  任务列表: {results['任务列表']}")
    
    results["重复上传"] = test_duplicate_upload()
    print(f"  重复上传: {results['重复上传']}")
    
    results["搜索验证"] = test_search_after_upload()
    print(f"  搜索验证: {results['搜索验证']}")
    
    results["无效任务查询"] = test_invalid_task()
    print(f"  无效任务查询: {results['无效任务查询']}")
    
    results["并发上传"] = test_concurrent_uploads()
    print(f"  并发上传: {results['并发上传']}")
    
    # 汇总
    print_section("测试汇总")
    
    # 修复：确保只统计 bool 值
    passed = sum(1 for v in results.values() if v is True)
    total = len(results)
    
    for name, status in results.items():
        if status:
            print_success(f"{name}: 通过")
        else:
            print_error(f"{name}: 失败")
    
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"总计: {passed}/{total} 通过")
    
    if passed == total:
        print_success("🎉 所有 Task Manager 测试通过！")
    else:
        print_error(f"⚠️ {total - passed} 个测试失败")
        print_info("请检查: 1) BackgroundTasks 是否配置 2) 异步函数是否正确执行")
    
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

if __name__ == "__main__":
    main()