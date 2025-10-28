"""
Quick check to verify the supervisor agent is running with conversational endpoints
"""

import requests
import sys

BASE_URL = "http://localhost:8000"

def check_server():
    """Check if supervisor agent is running"""
    print("🔍 Checking supervisor agent status...\n")
    
    try:
        # Check if server is running
        response = requests.get(f"{BASE_URL}/health", timeout=2)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"⚠️ Server responded with status {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("❌ Server is NOT running")
        print(f"\n   Please start the supervisor agent:")
        print(f"   cd supervisor-agent")
        print(f"   python supervisor_agent.py")
        return False
    except Exception as e:
        print(f"❌ Error connecting: {e}")
        return False
    
    # Check if /chat endpoint exists
    try:
        response = requests.post(
            f"{BASE_URL}/chat",
            json={"message": "test"},
            timeout=5
        )
        
        if response.status_code == 404:
            print("❌ /chat endpoint NOT FOUND")
            print(f"\n   The supervisor agent needs to be RESTARTED with the new code:")
            print(f"   1. Stop the current supervisor agent (Ctrl+C in its terminal)")
            print(f"   2. cd supervisor-agent")
            print(f"   3. python supervisor_agent.py")
            print(f"\n   Make sure you're running the file with conversational endpoints!")
            return False
        elif response.status_code in [200, 500]:  # 500 might be from OpenAI key, but endpoint exists
            print("✅ /chat endpoint is available")
            return True
        else:
            print(f"⚠️ /chat endpoint responded with status {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking /chat endpoint: {e}")
        return False

def main():
    print("="*70)
    print("SUPERVISOR AGENT CONVERSATIONAL ENDPOINT CHECK")
    print("="*70 + "\n")
    
    if check_server():
        print("\n" + "="*70)
        print("✅ ALL CHECKS PASSED - Ready to test!")
        print("="*70)
        print("\nYou can now run: python test_conversation.py")
        return 0
    else:
        print("\n" + "="*70)
        print("❌ CHECKS FAILED - Please fix the issues above")
        print("="*70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
