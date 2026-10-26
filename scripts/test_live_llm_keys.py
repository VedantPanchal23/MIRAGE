import os
import httpx
from dotenv import load_dotenv

load_dotenv(".env")
groq_key = os.getenv("GROQ_API_KEY")

for model in ["allam-2-7b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]:
    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in exactly 5 words."}],
                "max_tokens": 20,
            },
            timeout=10.0,
        )
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            print(f"[GROQ OK] {model}: {content}")
        else:
            print(f"[GROQ FAIL] {model} ({r.status_code}): {r.text[:100]}")
    except Exception as e:
        print(f"[GROQ ERR] {model}: {e}")

openrouter_key = os.getenv("OPENROUTER_API_KEY")
for model in ["meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-chat"]:
    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {openrouter_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say hello in exactly 5 words."}],
                "max_tokens": 20,
            },
            timeout=10.0,
        )
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            print(f"[OPENROUTER OK] {model}: {content}")
        else:
            print(f"[OPENROUTER FAIL] {model} ({r.status_code}): {r.text[:100]}")
    except Exception as e:
        print(f"[OPENROUTER ERR] {model}: {e}")
