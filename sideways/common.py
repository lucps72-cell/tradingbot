import datetime
from time import time
import time
import re
import requests
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

def is_time_between(start_time, end_time, now=None):
    """
    start_time, end_time: time 객체 또는 'HH:MM' 문자열
    now: time 객체 (기본값: 현재 시간)
    """
    if now is None:
        now = datetime.datetime.now().time()
    if isinstance(start_time, str):
        start_time = time.fromisoformat(start_time)
    if isinstance(end_time, str):
        end_time = time.fromisoformat(end_time)
    # 자정 넘김 구간 처리
    if start_time <= end_time:
        return start_time <= now <= end_time
    else:
        return now >= start_time or now <= end_time

# 음성 알림 함수 (pyttsx3 필요)
def play_voice_alert(message: str):
    """
    주어진 메시지를 음성으로 출력합니다. (pyttsx3 필요)
    """
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty('rate', 130)  # 음성 속도 느리게
        engine.say(message)
        engine.runAndWait()
    except Exception as e:
        print(f"[Voice Alert Error] {e}")

# 음성 알림 함수 (pyttsx3 필요)
def play_voice_alert_signal(message_key1: str, message_key2: str):
    """
    주어진 메시지를 음성으로 출력합니다. (pyttsx3 필요)
    """

    if message_key2 and message_key2 == "uptrend":
        message = f"{message_key1} 상승"
    elif message_key2 and message_key2 == "downtrend":
        message = f"{message_key1} 하락"
    else:
        return  # 빈 메시지인 경우 음성 알림 생략

    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty('rate', 130)  # 음성 속도 느리게
        engine.say(message)
        engine.runAndWait()
    except Exception as e:
        print(f"[Voice Alert Error] {e}")


def send_telegram(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print('[텔레그램 전송 실패] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.')
        return
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': chat_id, 'text': message}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"[텔레그램 전송 실패] {e}")

def send_email(subject, body, to_email, smtp_server, smtp_port, smtp_user, smtp_pass):
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_email
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
    except Exception as e:
        print(f"[이메일 전송 실패] {e}")
