import os
import sys
from core.code_rag import CodeRAGEngine
import logging

logging.basicConfig(level=logging.INFO)

def verify_jina():
    print("--- Verifying Jina Model Loading ---")
    try:
        # 使用一个测试项目名
        engine = CodeRAGEngine(project_name="test_verify")
        # 强制加载模型
        engine._load_model()
        if engine.model:
            print("✅ Jina model loaded successfully!")
            print(f"Model ID: {engine.model.get_sentence_embedding_dimension()} dimensions.")
        else:
            print("❌ Model loading failed (engine.model is None)")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error during Jina model loading: {e}")
        sys.exit(1)

if __name__ == "__main__":
    verify_jina()
