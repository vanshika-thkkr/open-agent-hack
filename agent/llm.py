# Power layer: every model call goes through Meterless Nightshift.
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ["METERLESS_BASE_URL"].rstrip("/")
TOKEN = os.environ["METERLESS_RUNTIME_TOKEN"]
MODEL = os.environ.get("METERLESS_MODEL", "meterless/auto")
APP = os.environ.get("METERLESS_APP", "hackathon-demo")


def chat(messages, tools=None, temperature=0.2):
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
    last = None
    for attempt in range(3):
        r = requests.post(f"{BASE}/chat/completions", headers=headers, json=body, timeout=180)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]
        last = f"{r.status_code}: {r.text[:600]}"
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        break
    raise RuntimeError(f"Nightshift request failed: {last}")