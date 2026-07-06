"""
通知推送 —— 钉钉 / 企业微信 Webhook

配置: .env 中设 DINGTALK_WEBHOOK / WECOM_WEBHOOK
"""
import requests
import os
from app.logger import logger

NOTIFY_ENABLED = os.getenv("NOTIFY_ENABLED", "false").lower() == "true"
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")


def send_dingtalk(title: str, content: str) -> bool:
    """发送钉钉机器人消息"""
    if not DINGTALK_WEBHOOK:
        return False
    try:
        resp = requests.post(DINGTALK_WEBHOOK, json={
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"## {title}\n\n{content}"}
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"钉钉推送失败: {e}")
        return False


def send_wecom(title: str, content: str) -> bool:
    """发送企业微信机器人消息"""
    if not WECOM_WEBHOOK:
        return False
    try:
        resp = requests.post(WECOM_WEBHOOK, json={
            "msgtype": "markdown",
            "markdown": {"content": f"## {title}\n{content}"}
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"企微推送失败: {e}")
        return False


def notify(title: str, content: str):
    """同时推送到所有已配置的通知渠道"""
    if not NOTIFY_ENABLED:
        return
    logger.info(f"通知推送: {title}")
    send_dingtalk(title, content)
    send_wecom(title, content)
