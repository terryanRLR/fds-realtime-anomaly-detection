import os
import sys
import requests
import smtplib
from email.message import EmailMessage
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# .env 파일 로드 (.env가 같은 폴더에 있어야 함)
load_dotenv()

# Windows 한글 입출력 깨짐 방지
sys.stdout.reconfigure(encoding='utf-8')

# MCP 서버 이름 지정
mcp = FastMCP("NotifierServer")


@mcp.tool()
def send_slack_message(text: str) -> str:
    """Send an urgent notification message to the team Slack channel."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return "Error: SLACK_WEBHOOK_URL is not set in environment variables."

    response = requests.post(webhook_url, json={"text": text}, timeout=10)  # 🐛 FIX(v5): 무한 대기 방지
    if response.status_code == 200:
        return "Slack message successfully sent!"
    return f"Failed to send Slack: {response.status_code} / {response.text}"


@mcp.tool()
def send_email(to_address: str, subject: str, body_text: str) -> str:
    """Send an email to a specific recipient."""
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    if not smtp_user or not smtp_pass:
        return "Error: SMTP_USER or SMTP_PASS is not set in environment variables."

    # 한글 본문 깨짐 방지를 위해 utf-8 명시
    msg = EmailMessage()
    msg.set_content(body_text, charset="utf-8")
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_address

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=15) as server:  # 🐛 FIX(v5)
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return f"Email successfully sent to {to_address}."
    except Exception as e:
        return f"Email failed: {str(e)}"


if __name__ == "__main__":
    # stdio 방식으로 MCP 서버 실행 (Claude Desktop 연동 표준)
    mcp.run(transport="stdio")
