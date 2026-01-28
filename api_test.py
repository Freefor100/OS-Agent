import os
import sys
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

def main():
    # 1. Load environment variables
    load_dotenv()
    
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE")
    
    
    if not api_key:
        print("Error: OPENAI_API_KEY not found in .env")
        return

    # 2. Select Model
    default_model = "qwen/qwen3-coder"
    if len(sys.argv) > 1:
        model_name = sys.argv[1]
    else:
        # Prompt user if no argument provided
        user_input = input(f"Enter model name (default: {default_model}): ").strip()
        model_name = user_input if user_input else default_model

    print(f"Testing with model: {model_name}")

    # 3. Initialize ChatOpenAI
    try:
        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base,
            temperature=0.7
        )
        
        # 4. specific test
        print("\nSending test message...")
        messages = [HumanMessage(content="Hello, please reply with 'API Test Successful!'.")]
        
        response = llm.invoke(messages)
        
        print("\nResponse:")
        print("-" * 40)
        print(response.content)
        print("-" * 40)
        print("Test completed successfully.")

    except Exception as e:
        print("\nError during API test:")
        print(e)

if __name__ == "__main__":
    main()
