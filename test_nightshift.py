import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument(
    "--models",
    action="store_true",
    help="List model ids from GET {base}/models instead of sending a chat completion",
)
args = parser.parse_args()

base_url = os.environ.get("METERLESS_BASE_URL", "").rstrip("/")
token = os.environ.get("METERLESS_RUNTIME_TOKEN", "")
model = os.environ.get("METERLESS_MODEL", "")

if not base_url:
    raise SystemExit("METERLESS_BASE_URL is missing from .env")
if not token:
    raise SystemExit("METERLESS_RUNTIME_TOKEN is missing from .env")

headers = {
    "Authorization": f"Bearer {token}",
    "meterless-app": "hackathon-demo",
    "meterless-scope": "user",
    "Content-Type": "application/json",
}


def fail_if_not_ok(response):
    if response.status_code != 200:
        body = response.text[:1500].replace(token, "<redacted>")
        print(response.status_code)
        print(body)
    response.raise_for_status()


def print_routing(data):
    if "model" in data:
        print(data["model"])
    meterless = data.get("meterless")
    if not isinstance(meterless, dict):
        return
    for key in ("requested_model", "provider_model", "routed_model", "request_id"):
        if key in meterless:
            print(f"{key}: {meterless[key]}")


if args.models:
    response = requests.get(f"{base_url}/models", headers=headers, timeout=60)
    fail_if_not_ok(response)
    data = response.json()
    for item in data.get("data", []):
        model_id = item.get("id")
        if model_id:
            print(model_id)
    print_routing(data)
    raise SystemExit(0)

if not model:
    raise SystemExit("METERLESS_MODEL is missing from .env")

response = requests.post(
    f"{base_url}/chat/completions",
    headers=headers,
    json={
        "model": model,
        "messages": [
            {"role": "user", "content": "Reply with one sentence confirming this works."}
        ],
    },
    timeout=60,
)
fail_if_not_ok(response)

data = response.json()
reply = data["choices"][0]["message"]["content"]
print(reply)
print_routing(data)
