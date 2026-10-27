# Power layer: every model call goes through Meterless Nightshift (Nemotron inside).
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("METERLESS_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("METERLESS_RUNTIME_TOKEN", "")
MODEL = os.environ.get("METERLESS_MODEL", "meterless/auto")
APP = os.environ.get("METERLESS_APP", "hackathon-demo")


class ModelUnavailable(RuntimeError):
    """Nightshift could not return an answer after several tries."""


def _strip_think(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def chat(messages, tools=None, temperature=0.2):
    if not BASE or not TOKEN:
        raise ModelUnavailable("METERLESS_BASE_URL or METERLESS_RUNTIME_TOKEN is missing from .env")
    body = {"model": MODEL, "messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "meterless-app": APP,
        "meterless-scope": "user",
    }
    last = "no attempt made"
    for attempt in range(4):
        try:
            r = requests.post(f"{BASE}/chat/completions", headers=headers, json=body, timeout=180)
        except requests.RequestException as e:
            last = f"network error: {str(e)[:200]}"
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                msg = r.json()["choices"][0]["message"]
            except Exception:
                last = "malformed reply from Nightshift"
                time.sleep(3 * (attempt + 1))
                continue
            if msg.get("content"):
                msg["content"] = _strip_think(msg["content"])
            return msg
        last = f"HTTP {r.status_code}: {r.text[:300]}"
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        break
    raise ModelUnavailable(f"Nightshift request failed: {last}")
