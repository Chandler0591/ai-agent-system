"""
Locust 压力测试脚本
运行: locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=10
"""
from locust import HttpUser, task, between


class AIAgentUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """用户初始化 —— 获取 token"""
        try:
            resp = self.client.post(
                "/api/token",
                data={"username": "testuser", "password": "testpass"}
            )
            if resp.ok:
                self.token = resp.json()["access_token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
            else:
                self.token = None
                self.headers = {}
        except Exception:
            self.token = None
            self.headers = {}

    # ========== 基础接口 ==========

    @task(3)
    def health_check(self):
        self.client.get("/api/health")

    @task(2)
    def get_stats(self):
        self.client.get("/api/stats")

    @task(2)
    def search_knowledge(self):
        self.client.get("/api/rag/search", params={"q": "卡口系统", "top_k": 3})

    @task(2)
    def get_documents(self):
        self.client.get("/api/kb/documents")

    # ========== Agent 接口 ==========

    @task(5)
    def agent_chat(self):
        """普通对话"""
        self.client.post(
            "/api/agent/run",
            json={"message": "你好，请介绍一下自己", "mode": "auto"},
            headers=self.headers,
            timeout=30,
        )

    @task(3)
    def agent_with_tool(self):
        """工具调用"""
        self.client.post(
            "/api/agent/run",
            json={"message": "北京天气怎么样", "mode": "auto"},
            headers=self.headers,
            timeout=30,
        )

    @task(2)
    def agent_rag_question(self):
        """知识库问题"""
        self.client.post(
            "/api/agent/run",
            json={"message": "什么是智能卡口系统", "mode": "auto"},
            headers=self.headers,
            timeout=60,
        )

    # ========== 认证 ==========

    @task(1)
    def login(self):
        self.client.post(
            "/api/token",
            data={"username": "perftest", "password": "perfpass"}
        )

    @task(1)
    def get_me(self):
        self.client.get("/api/me", headers=self.headers)

    # ========== 监控 ==========

    @task(1)
    def metrics(self):
        self.client.get("/api/metrics")


class ReadOnlyUser(HttpUser):
    """只读用户 —— 模拟文档浏览者"""
    wait_time = between(2, 5)

    @task(5)
    def browse_docs(self):
        self.client.get("/api/kb/documents")

    @task(3)
    def search(self):
        queries = ["卡口", "车牌识别", "人工智能", "数据分析", "系统架构"]
        import random
        q = random.choice(queries)
        self.client.get(f"/api/rag/search?q={q}&top_k=3")

    @task(2)
    def stats(self):
        self.client.get("/api/stats")


class HeavyUser(HttpUser):
    """重度用户 —— 频繁 Agent 调用"""
    wait_time = between(0.5, 1.5)

    @task(5)
    def heavy_chat(self):
        questions = [
            "分析卡口系统的优势",
            "对比车牌识别技术",
            "如何提升系统性能",
            "AI在交通领域的应用",
            "当前时间",
        ]
        import random
        q = random.choice(questions)
        self.client.post(
            "/api/agent/run",
            json={"message": q, "mode": "auto"},
            timeout=60,
        )
