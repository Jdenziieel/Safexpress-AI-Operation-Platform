"""
Test script for log integration (SQLite storage + logging_config)
"""

import os
import sys

# Test imports
print("Testing imports...")
try:
    from logging_config import (
        LogLevel, StructuredLogger, TokenTracker, 
        request_context, create_logger, get_log_storage,
        DEFAULT_LOG_FILE
    )
    print("[OK] logging_config imports successful")
except Exception as e:
    print(f"[FAIL] logging_config import error: {e}")
    sys.exit(1)

try:
    from log_storage import LogStorage
    print("[OK] log_storage imports successful")
except Exception as e:
    print(f"[FAIL] log_storage import error: {e}")
    sys.exit(1)

try:
    from log_schema import (
        BaseLogEntry, LLMLogEntry, AgentLogEntry, 
        ProgressLogEntry, TokenUsageSchema
    )
    print("[OK] log_schema imports successful (LogLevel imported from logging_config)")
except Exception as e:
    print(f"[FAIL] log_schema import error: {e}")
    sys.exit(1)

# Test LogStorage directly
print("\nTesting LogStorage...")
test_db = "test_integration.db"
try:
    storage = LogStorage(test_db)
    print("[OK] LogStorage initialized")
except Exception as e:
    print(f"[FAIL] LogStorage initialization: {e}")
    sys.exit(1)

# Test insert_log with dict parameter
print("\nTesting insert_log with dict...")
try:
    log_entry = {
        "timestamp": "2025-01-01T00:00:00Z",
        "level": "INFO",
        "logger": "test",
        "message": "Test message from dict",
        "request_id": "req_test_001",
        "component": "test_component",
        "data": {"key": "value"}
    }
    log_id = storage.insert_log(log_entry)
    print(f"[OK] Inserted log with ID: {log_id}")
except Exception as e:
    print(f"[FAIL] insert_log with dict: {e}")
    sys.exit(1)

# Test get_logs returns tuple
print("\nTesting get_logs returns tuple (logs, total)...")
try:
    result = storage.get_logs(limit=10)
    assert isinstance(result, tuple), "get_logs should return tuple"
    logs, total = result
    assert isinstance(logs, list), "First element should be list"
    assert isinstance(total, int), "Second element should be int"
    print(f"[OK] get_logs returned {len(logs)} logs, total: {total}")
except Exception as e:
    print(f"[FAIL] get_logs: {e}")
    sys.exit(1)

# Test search_logs
print("\nTesting search_logs...")
try:
    logs, total = storage.search_logs("Test message")
    print(f"[OK] search_logs found {total} matches")
except Exception as e:
    print(f"[FAIL] search_logs: {e}")
    sys.exit(1)

# Test get_token_summary
print("\nTesting get_token_summary...")
try:
    summary = storage.get_token_summary()
    assert isinstance(summary, dict), "Should return dict"
    print(f"[OK] Token summary: {summary.get('totals', {})}")
except Exception as e:
    print(f"[FAIL] get_token_summary: {e}")
    sys.exit(1)

# Test get_request_analytics
print("\nTesting get_request_analytics...")
try:
    analytics = storage.get_request_analytics()
    assert isinstance(analytics, list), "Should return list"
    print(f"[OK] Request analytics: {len(analytics)} requests")
except Exception as e:
    print(f"[FAIL] get_request_analytics: {e}")
    sys.exit(1)

# Test clear_logs
print("\nTesting clear_logs...")
try:
    deleted = storage.clear_logs()
    print(f"[OK] Cleared {deleted} logs")
except Exception as e:
    print(f"[FAIL] clear_logs: {e}")
    sys.exit(1)

# Test logging_config integration with SQLite
print("\nTesting logging_config SQLite integration...")
try:
    logger = create_logger("test_integration")
    with request_context(conversation_id="conv_test_123") as req_id:
        logger.info("Integration test message", component="test")
        logger.llm_call(
            model="gpt-4o",
            operation="test_operation",
            input_tokens=100,
            output_tokens=50,
            duration_ms=500.0,
            tier="0.5"
        )
        logger.progress(
            "Test progress",
            current_step=1,
            total_steps=3,
            step_name="testing"
        )
        logger.request_summary()
    print(f"[OK] Logged with request_id: {req_id}")
except Exception as e:
    print(f"[FAIL] logging_config integration: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Verify logs in SQLite
print("\nVerifying logs in SQLite...")
try:
    logs, total = storage.get_logs(limit=10)
    print(f"[OK] Found {total} logs in database")
    
    # Check if logs are properly stored
    for log in logs[-3:]:  # Check last 3 logs
        print(f"  - [{log.get('level')}] {log.get('message')[:50]}...")
except Exception as e:
    print(f"[FAIL] Verification: {e}")
    sys.exit(1)

# Cleanup test database
print("\nCleaning up...")
try:
    os.remove(test_db)
    print(f"[OK] Removed test database: {test_db}")
except Exception as e:
    print(f"[WARN] Could not remove test db: {e}")

print("\n" + "="*50)
print("ALL TESTS PASSED!")
print("="*50)
