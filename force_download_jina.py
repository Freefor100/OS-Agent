import os
import sys
import time
from huggingface_hub import hf_hub_download

# 配置加速和镜像
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
os.environ["HF_HUB_READ_TIMEOUT"] = "1000"

MODEL_ID = "jinaai/jina-embeddings-v2-base-code"
FILENAME = "model.safetensors"

def download_with_retry(retries=20):
    for i in range(retries):
        try:
            print(f"\n[Attempt {i+1}/{retries}] Starting/Resuming download of {FILENAME}...")
            path = hf_hub_download(
                repo_id=MODEL_ID,
                filename=FILENAME,
                resume_download=True,
                etag_timeout=100
            )
            print(f"\n✅ Success! Model saved to: {path}")
            return True
        except Exception as e:
            print(f"\n❌ Download interrupted: {e}")
            print("Waiting 5 seconds before next retry...")
            time.sleep(5)
    return False

if __name__ == "__main__":
    print(f"Targeting Mirror: {os.environ['HF_ENDPOINT']}")
    success = download_with_retry()
    if not success:
        print("\n💥 All retry attempts failed. Please check your internet connection.")
        sys.exit(1)
