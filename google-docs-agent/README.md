# Google Docs Agent 📝

A LangChain-powered AI agent that can create and manage Google Docs using natural language commands. Built for the SafexpressOps Capstone Project.

## 🎯 Overview

This agent uses:
- **LangChain**: Framework for building AI agents
- **GPT-4**: The "brain" that understands user requests
- **Google Docs API**: To actually create and modify documents
- **OAuth 2.0**: Secure authentication with user's Google account

## 🏗️ Architecture

```
User Request → LangChain Agent (GPT-4) → Tool Selection → Google Docs API → Response
```

### Components

1. **`agent.py`** - Main agent orchestration
   - Sets up the LangChain agent with GPT-4
   - Defines the agent's behavior and personality
   - Handles the conversation flow

2. **`tools.py`** - Google Docs tools
   - `create_google_doc()` - Creates new documents
   - `add_text_to_doc()` - Adds content to documents
   - `read_google_doc()` - Reads document content
   - `get_google_service()` - Helper for Google API authentication

3. **`test_agent.py`** - Testing utilities
4. **`setup_check.py`** - Validates your setup

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- OpenAI API key
- Google Cloud Console project with Docs API enabled
- Google OAuth credentials

### Installation

1. **Clone the repository**
   ```bash
   cd google-docs-agent
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   
   Create a `.env` file in this directory:
   ```env
   # OpenAI API Key
   OPENAI_API_KEY=sk-...

   # Google OAuth Credentials (from Google Cloud Console)
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret

   # For testing: Get these from OAuth flow
   GOOGLE_ACCESS_TOKEN=your-access-token
   GOOGLE_REFRESH_TOKEN=your-refresh-token
   ```

4. **Run the agent**
   ```bash
   python agent.py
   ```

## 🔧 Setup Guide

### Step 1: Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Google Docs API:
   - Navigate to "APIs & Services" → "Library"
   - Search for "Google Docs API"
   - Click "Enable"
4. Create OAuth 2.0 Credentials:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: "Web application"
   - Add authorized redirect URIs (e.g., `http://localhost:8000/callback`)
   - Save your Client ID and Client Secret

### Step 2: OpenAI API Setup

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Create an API key
3. Add to your `.env` file

### Step 3: Get OAuth Tokens (For Testing)

To test with your actual Google account, you need to get OAuth tokens. Here's a simple way:

```python
# Run this once to get your tokens
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive'
]

flow = InstalledAppFlow.from_client_secrets_file(
    'credentials.json',  # Download from Google Cloud Console
    SCOPES
)
creds = flow.run_local_server(port=0)

print(f"Access Token: {creds.token}")
print(f"Refresh Token: {creds.refresh_token}")
```

## 💡 Usage Examples

### Example 1: Create a Document

```python
from agent import create_docs_agent

credentials = {
    'access_token': 'your-access-token',
    'refresh_token': 'your-refresh-token'
}

agent = create_docs_agent(credentials)

response = agent.invoke({
    "input": "Create a document called 'Meeting Notes'"
})

print(response['output'])
# Output: "I've created 'Meeting Notes' for you! Here's the link: ..."
```

### Example 2: Natural Language Commands

The agent understands various ways of asking:

```python
# All of these work:
"Create a new doc called Project Plan"
"Make a document named Budget 2025"
"I need a Google Doc for my presentation"
"Can you create a document titled Research Notes?"
```

## 🔌 Django Integration

To integrate with your Django backend:

```python
# views.py
from google_docs_agent.agent import create_docs_agent

def create_document(request):
    # Get user's OAuth tokens from session/database
    credentials = {
        'access_token': request.user.google_access_token,
        'refresh_token': request.user.google_refresh_token
    }
    
    # Create agent with user's credentials
    agent = create_docs_agent(credentials)
    
    # Get user's request
    user_message = request.POST.get('message')
    
    # Execute
    response = agent.invoke({"input": user_message})
    
    return JsonResponse({
        'response': response['output']
    })
```

## 🧪 Testing

### Run Setup Check
```bash
python setup_check.py
```

This will verify:
- ✅ All packages installed
- ✅ Environment variables set
- ✅ Google API credentials valid
- ✅ OpenAI API key working

### Run Tests
```bash
python test_agent.py
```

### Manual Testing
```bash
python agent.py
```

## 🐛 Troubleshooting

### Error: "401 Unauthorized"
**Problem**: OAuth tokens are invalid or expired

**Solutions**:
- Regenerate your access token
- Check that refresh_token is valid
- Verify GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are correct

### Error: "403 Forbidden"
**Problem**: Google Docs API not enabled

**Solutions**:
- Go to Google Cloud Console
- Enable "Google Docs API" for your project
- Wait a few minutes for changes to propagate

### Error: "Module not found"
**Problem**: Missing dependencies

**Solution**:
```bash
pip install -r requirements.txt
```

### Error: "Invalid API Key"
**Problem**: OpenAI API key is wrong

**Solutions**:
- Check your `.env` file
- Verify the key at platform.openai.com
- Make sure there are no extra spaces

### Agent Not Using Tools
**Problem**: Agent responds but doesn't create documents

**Solutions**:
- Check `verbose=True` in AgentExecutor to see thinking process
- Verify the tool decorator is applied correctly
- Make sure credentials_dict is being passed to tools

## 📚 Key Concepts

### What is a Tool?
A **tool** is a function that the AI agent can call. The `@tool` decorator tells LangChain:
- What the function does (from the docstring)
- What parameters it needs
- When it should be used

### What is an Agent?
An **agent** is an AI that can:
1. Understand user requests
2. Decide which tool(s) to use
3. Call those tools
4. Return results to the user

Think of it as "ChatGPT with the ability to actually DO things"

### OAuth Flow
```
User → Login with Google → Approval → Tokens → Store in DB
                                                      ↓
                                              Pass to Agent
                                                      ↓
                                              Use for API calls
```

## 🎓 Learning Resources

- [LangChain Documentation](https://python.langchain.com/)
- [Google Docs API Guide](https://developers.google.com/docs/api)
- [OAuth 2.0 Explained](https://oauth.net/2/)
- [OpenAI API Reference](https://platform.openai.com/docs)

## 🚧 Future Enhancements

- [ ] Add text formatting tools (bold, italic, headings)
- [ ] Document sharing capabilities
- [ ] Search and edit existing documents
- [ ] Export to PDF
- [ ] Batch operations
- [ ] Confidence scoring for agent responses
- [ ] Multi-language support

## 📝 License

MIT License - See LICENSE file for details

## 🤝 Contributing

This is a capstone project, but feedback is welcome!

## 👥 Author

SafexpressOps Capstone Project
October 2025

---

**Questions?** Check the troubleshooting section or review the inline comments in `agent.py` and `tools.py`.