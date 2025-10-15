# Lambda Deployment Guide - Google Docs Agent

## The Problem
Your Lambda function was failing with:
```
OpenAIError: The api_key client option must be set either by passing api_key to the client or by setting the OPENAI_API_KEY environment variable
```

**Root Cause**: The original `agent.py` used `os.getenv("OPENAI_API_KEY")` which doesn't work reliably in Lambda without explicit passing.

## The Solution

### Option 1: Use Lambda-Specific Files (Recommended)

1. **Upload these files to Lambda**:
   - `lambda_function.py` (updated version)
   - `agent_lambda.py` (new Lambda-compatible agent)
   - `tools.py`
   - `confidence.py`

2. **Update your Lambda handler import**:
   ```python
   from agent_lambda import create_docs_agent
   ```

3. **Set Environment Variables in Lambda Console**:
   - `OPENAI_API_KEY` = your-openai-key

4. **The fix**: The new code explicitly passes the API key:
   ```python
   openai_api_key = os.environ.get('OPENAI_API_KEY')
   agent = create_docs_agent(credentials_dict, openai_api_key=openai_api_key)
   ```

### Option 2: Modify Original agent.py

If you want to keep using `agent.py`, modify the `create_docs_agent` function:

```python
def create_docs_agent(credentials_dict: Dict, openai_api_key: str = None):
    # Use explicit key or fall back to environment
    api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        raise ValueError("OpenAI API key is required")
    
    llm = ChatOpenAI(
        model="gpt-4",
        temperature=0,
        openai_api_key=api_key  # Pass explicitly
    )
    # ... rest of code
```

## Verification Steps

### 1. Check Environment Variable in Lambda Console
- Go to Lambda Console → Configuration → Environment variables
- Verify `OPENAI_API_KEY` is set

### 2. Test with Simple Event
```json
{
  "tool": "create_doc",
  "inputs": {
    "title": "Test Document from Lambda"
  },
  "credentials": {
    "access_token": "your-google-access-token",
    "refresh_token": "your-google-refresh-token"
  }
}
```

### 3. Expected Success Response
```json
{
  "statusCode": 200,
  "body": {
    "success": true,
    "result": {
      "document_id": "...",
      "document_url": "https://docs.google.com/...",
      "title": "Test Document from Lambda"
    }
  }
}
```

## Common Lambda Environment Issues

### Issue: Environment variables not loading
**Solution**: 
- Don't use `load_dotenv()` in Lambda
- Set variables directly in Lambda console
- Pass sensitive values as parameters

### Issue: Import errors
**Solution**:
- Use Lambda Layers for dependencies
- Or bundle all packages in deployment ZIP
- Ensure correct file structure

### Issue: Timeout
**Solution**:
- Increase Lambda timeout (default 3s → 30s+)
- Memory: 128MB → 512MB for AI operations

## Deployment Checklist

- [ ] Environment variable `OPENAI_API_KEY` set in Lambda console
- [ ] Using `agent_lambda.py` or modified `agent.py` with explicit API key parameter
- [ ] Lambda timeout set to at least 30 seconds
- [ ] Lambda memory set to at least 256 MB (512 MB recommended)
- [ ] All dependencies in Lambda Layer or deployment package
- [ ] Test event configured with valid Google credentials

## File Differences

### Old agent.py
```python
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0,
    openai_api_key=os.getenv("OPENAI_API_KEY")  # ❌ Unreliable in Lambda
)
```

### New agent_lambda.py
```python
def create_docs_agent(credentials_dict: dict, openai_api_key: str = None):
    if not openai_api_key:
        raise ValueError("openai_api_key is required for Lambda deployment")
    
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=openai_api_key  # ✅ Explicitly passed
    )
```

## Next Steps

1. **Update Lambda**: Replace files with new versions
2. **Verify Env Vars**: Double-check Lambda console settings
3. **Test**: Run a simple test event
4. **Monitor**: Check CloudWatch logs for any errors
5. **Scale**: Adjust timeout/memory as needed

## Troubleshooting

If you still get errors:

1. **Print environment in Lambda**:
   ```python
   print("Environment variables:", dict(os.environ))
   ```

2. **Check CloudWatch Logs**: Look for exact error messages

3. **Verify API Key Format**: Should start with `sk-proj-...`

4. **Test Locally First**: Ensure code works before deploying

---

**Key Takeaway**: Lambda requires explicit parameter passing for sensitive values. Don't rely on `os.getenv()` alone - pass API keys as function parameters.
