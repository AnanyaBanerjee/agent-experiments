"""Quick test to check if fal.ai is working correctly."""

import os
import json
import time
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FAL_KEY = os.environ.get("FAL_KEY")

if not FAL_KEY:
    print("❌ FAL_KEY not found in .env")
    exit(1)

print(f"✅ FAL_KEY found: {FAL_KEY[:8]}...")
print("\n1. Submitting request to fal.ai queue...")

response = httpx.post(
    "https://queue.fal.run/fal-ai/flux/schnell",
    headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
    json={
        "prompt": "a red apple on a white table",
        "image_size": "landscape_4_3",
        "num_images": 1,
        "enable_safety_checker": True,
    },
    timeout=30.0,
)
queue = response.json()
print(f"   Status: {queue['status']} | request_id: {queue['request_id']}")

print("\n2. Polling for completion...")
while True:
    status = httpx.get(
        queue["status_url"],
        headers={"Authorization": f"Key {FAL_KEY}"},
        timeout=30.0,
    ).json()
    print(f"   {status['status']}")
    if status["status"] == "COMPLETED":
        break
    if status["status"] == "FAILED":
        print("❌ Generation failed")
        exit(1)
    time.sleep(2)

print("\n3. Fetching result...")
result = httpx.get(
    queue["response_url"],
    headers={"Authorization": f"Key {FAL_KEY}"},
    timeout=30.0,
).json()
image_url = result["images"][0]["url"]
print(f"   Image URL: {image_url}")

print("\n4. Downloading and saving to images/test.png ...")
Path("images").mkdir(exist_ok=True)
image_data = httpx.get(image_url, timeout=60.0).content
Path("images/test.png").write_bytes(image_data)
print(f"   Saved {len(image_data)} bytes → images/test.png")
print("\n✅ fal.ai is working correctly!")
