import os
import sys
from core.code_rag import CodeRAGEngine
import logging

logging.basicConfig(level=logging.INFO)

def verify_jina():
    print("--- Verifying Jina Model Loading (Parallel Test) ---")
    try:
        engine = CodeRAGEngine(project_name="test_verify")
        
        # 使用线程模拟并发加载
        import threading
        
        def load_task():
            engine._load_model()
            if engine.model:
                print(f"Thread {threading.current_thread().name}: ✅ Model loaded/accessed.")
            else:
                print(f"Thread {threading.current_thread().name}: ❌ Failed.")

        threads = []
        for i in range(5):
            t = threading.Thread(target=load_task, name=f"Loader-{i}")
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        if engine.model:
            print("✅ Overall test result: Jina model loaded successfully!")
            print(f"Model ID: {engine.model.get_sentence_embedding_dimension()} dimensions.")
            device = engine.model.device
            print(f"Device being used: {device}")
        else:
            print("❌ Overall test result: Model loading failed")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error during Jina model loading: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    verify_jina()
