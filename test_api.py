"""LLM API 连通性测试脚本"""

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

api_base = os.getenv("OPENAI_API_BASE")
api_key = os.getenv("OPENAI_API_KEY")
model = os.getenv("MODEL_NAME")

print(f"API Base : {api_base}")
print(f"API Key  : {api_key[:8]}...{api_key[-4:]}" if api_key else "API Key  : (未设置)")
print(f"Model    : {model}")
print("-" * 50)

client = OpenAI(api_key=api_key, base_url=api_base)

try:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": '说"测试成功"，不要说别的。'}],
        max_tokens=64,
    )
    reply = resp.choices[0].message.content.strip()
    usage = resp.usage
    print(f"回复     : {reply}")
    print(f"Tokens   : prompt={usage.prompt_tokens}  completion={usage.completion_tokens}  total={usage.total_tokens}")
    print("✅ API 连通正常")
except Exception as e:
    print(f"❌ 调用失败: {e}")
