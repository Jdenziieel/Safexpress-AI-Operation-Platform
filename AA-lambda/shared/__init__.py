"""AA-lambda shared brain modules.

Most files in this package are byte-for-byte copies of `supervisor-agent/`.
The only files allowed to differ are documented in `STRUCTURE.md`:
  - utils.py (call_agent_with_retry: httpx -> boto3.lambda.invoke)
  - config.py (AGENT_ENDPOINTS reads AGENT_LAMBDA_NAMES_JSON)
  - logging_config.py (set_request_context jwt parameter + Bearer header)
"""
