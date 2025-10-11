"""
=================================================================
GOOGLE DOCS AGENT - Setup Verification Script
=================================================================

This script checks that your environment is properly configured
before you start using the Google Docs agent.

Run this script to verify:
- All required packages are installed
- Environment variables are set correctly
- API credentials are valid

Usage: python setup_check.py
=================================================================
"""

import os
import sys
from pathlib import Path


def check_packages():
    """Check if all required packages are installed."""
    print("\n🔍 Checking installed packages...")
    
    required_packages = [
        ('langchain', 'langchain'),
        ('langchain_openai', 'langchain-openai'),
        ('langgraph', 'langgraph'),
        ('google.oauth2', 'google-auth'),
        ('googleapiclient', 'google-api-python-client'),
        ('openai', 'openai'),
        ('dotenv', 'python-dotenv')
    ]
    
    missing_packages = []
    
    for package_name, install_name in required_packages:
        try:
            __import__(package_name)
            print(f"  ✅ {install_name}")
        except ImportError:
            print(f"  ❌ {install_name} - NOT INSTALLED")
            missing_packages.append(install_name)
    
    if missing_packages:
        print(f"\n⚠️  Missing packages: {', '.join(missing_packages)}")
        print("   Install with: pip install -r requirements.txt")
        return False
    else:
        print("\n✅ All packages installed!")
        return True


def check_env_file():
    """Check if .env file exists."""
    print("\n🔍 Checking for .env file...")
    
    env_path = Path('.env')
    if env_path.exists():
        print("  ✅ .env file found")
        return True
    else:
        print("  ⚠️  .env file not found")
        print("     Copy .env.example to .env and fill in your values:")
        print("     cp .env.example .env")
        return False


def check_environment_variables():
    """Check if required environment variables are set."""
    print("\n🔍 Checking environment variables...")
    
    # Load .env file if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except:
        pass
    
    required_vars = {
        'OPENAI_API_KEY': 'OpenAI API key for GPT-4',
        'GOOGLE_CLIENT_ID': 'Google OAuth Client ID',
        'GOOGLE_CLIENT_SECRET': 'Google OAuth Client Secret'
    }
    
    optional_vars = {
        'GOOGLE_ACCESS_TOKEN': 'Google access token (for testing)',
        'GOOGLE_REFRESH_TOKEN': 'Google refresh token (for testing)'
    }
    
    missing_required = []
    all_good = True
    
    # Check required variables
    print("\n  Required variables:")
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value and value != f'your-{var.lower().replace("_", "-")}-here':
            print(f"    ✅ {var}")
        else:
            print(f"    ❌ {var} - {description}")
            missing_required.append(var)
            all_good = False
    
    # Check optional variables
    print("\n  Optional variables (for testing):")
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value and value != f'your-{var.lower().replace("_", "-")}-here':
            print(f"    ✅ {var}")
        else:
            print(f"    ⚠️  {var} - {description}")
    
    if missing_required:
        print(f"\n⚠️  Missing required variables: {', '.join(missing_required)}")
        print("   Set these in your .env file")
        return False
    
    return all_good


def check_openai_api():
    """Test OpenAI API connection."""
    print("\n🔍 Testing OpenAI API connection...")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key or api_key.startswith('your-'):
            print("  ⚠️  OpenAI API key not set")
            return False
        
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        # Try a simple API call
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Use cheaper model for testing
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5
        )
        
        print("  ✅ OpenAI API connection successful!")
        return True
        
    except Exception as e:
        print(f"  ❌ OpenAI API error: {e}")
        return False


def check_google_credentials():
    """Verify Google OAuth credentials are set."""
    print("\n🔍 Checking Google OAuth credentials...")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        
        if not client_id or client_id == 'your-client-id.apps.googleusercontent.com':
            print("  ⚠️  GOOGLE_CLIENT_ID not set")
            return False
        
        if not client_secret or client_secret == 'your-client-secret':
            print("  ⚠️  GOOGLE_CLIENT_SECRET not set")
            return False
        
        print("  ✅ Google OAuth credentials set")
        print("  ℹ️  Note: Can't verify validity without OAuth flow")
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def check_file_structure():
    """Check if all required files exist."""
    print("\n🔍 Checking project structure...")
    
    required_files = [
        'agent.py',
        'tools.py',
        'requirements.txt',
        'README.md'
    ]
    
    all_exist = True
    for file in required_files:
        if Path(file).exists():
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} - NOT FOUND")
            all_exist = False
    
    return all_exist


def main():
    """Run all checks."""
    print("=================================================================")
    print("GOOGLE DOCS AGENT - Setup Verification")
    print("=================================================================")
    
    checks = [
        ("File Structure", check_file_structure),
        ("Python Packages", check_packages),
        (".env File", check_env_file),
        ("Environment Variables", check_environment_variables),
        ("Google Credentials", check_google_credentials),
        ("OpenAI API", check_openai_api),
    ]
    
    results = {}
    for check_name, check_func in checks:
        try:
            results[check_name] = check_func()
        except Exception as e:
            print(f"\n❌ Error during {check_name} check: {e}")
            results[check_name] = False
    
    # Summary
    print("\n=================================================================")
    print("SUMMARY")
    print("=================================================================")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for check_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {check_name}")
    
    print(f"\n{passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All checks passed! You're ready to use the agent.")
        print("   Run: python agent.py")
    else:
        print("\n⚠️  Some checks failed. Please fix the issues above.")
        print("   See README.md for setup instructions.")
    
    print("\n=================================================================")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
