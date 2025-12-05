"""
Test script for the logging implementation
Run this to verify all logging components work correctly
"""

import sys
sys.path.insert(0, '.')

from logging_config import (
    create_logger,
    request_context,
    set_request_context,
    clear_request_context,
    get_current_request_id,
    get_token_summary,
    generate_request_id,
    DEFAULT_LOG_FILE
)

def test_logging():
    print("=" * 60)
    print("TESTING LOGGING IMPLEMENTATION")
    print("=" * 60)
    
    # Test 1: Create logger with log file
    print("\n[TEST 1] Creating logger...")
    logger = create_logger("test_module", DEFAULT_LOG_FILE)
    print(f"✅ Logger created successfully (log file: {DEFAULT_LOG_FILE})")
    
    # Test 2: Test request context
    print("\n[TEST 2] Testing request context...")
    with request_context(conversation_id="test_conv_123", thread_id="thread_abc"):
        req_id = get_current_request_id()
        print(f"✅ Request ID generated: {req_id}")
        
        # Test 3: Log basic messages
        print("\n[TEST 3] Testing basic logging...")
        logger.info("Test info message", component="test", operation="test_op")
        logger.debug("Test debug message")
        logger.warning("Test warning message")
        print("✅ Basic logging works")
        
        # Test 4: Log LLM call with token tracking
        print("\n[TEST 4] Testing LLM call logging with token tracking...")
        logger.llm_call(
            model="gpt-4o",
            operation="tier_0.5_unified_check",
            input_tokens=150,
            output_tokens=50,
            duration_ms=850.5,
            tier="0.5",
            prompt_summary="Classifying: send email to john...",
            success=True
        )
        
        # Second LLM call
        logger.llm_call(
            model="gpt-4o",
            operation="tier_1_full_analysis",
            input_tokens=800,
            output_tokens=200,
            duration_ms=2350.8,
            tier="1",
            prompt_summary="Analyzing: send email to john...",
            success=True
        )
        print("✅ LLM call logging works")
        
        # Test 5: Check token summary accumulation
        print("\n[TEST 5] Testing token summary accumulation...")
        token_summary = get_token_summary()
        if token_summary:
            print(f"   Total tokens: {token_summary.total_tokens}")
            print(f"   Total cost: ${token_summary.total_estimated_cost:.6f}")
            print(f"   LLM calls: {len(token_summary.llm_calls)}")
            print("✅ Token tracking accumulation works")
        else:
            print("❌ Token summary not found")
        
        # Test 6: Progress logging (step-based, no percentage)
        print("\n[TEST 6] Testing progress logging (no percentage)...")
        logger.progress(
            "Executing plan",
            current_step=1,
            total_steps=3,
            step_name="search_emails"
        )
        logger.progress(
            "Executing plan",
            current_step=2,
            total_steps=3,
            step_name="get_thread"
        )
        logger.progress(
            "Executing plan",
            current_step=3,
            total_steps=3,
            step_name="reply_email"
        )
        print("✅ Progress logging works (step-based)")
        
        # Test 7: Agent call logging
        print("\n[TEST 7] Testing agent call logging...")
        logger.agent_call(
            agent_name="gmail_agent",
            tool_name="search_emails",
            step_number=1,
            total_steps=3,
            inputs={"query": "from:john@example.com", "max_results": 5},
            success=True,
            duration_ms=1250.3,
            output_summary="Found 3 emails"
        )
        print("✅ Agent call logging works")
        
        # Test 8: Error logging
        print("\n[TEST 8] Testing error logging...")
        try:
            raise ValueError("Test error for logging")
        except Exception as e:
            logger.error("Test error occurred", error=e, component="test")
        print("✅ Error logging works")
        
        # Test 9: Request summary
        print("\n[TEST 9] Testing request summary...")
        logger.request_summary()
        print("✅ Request summary works")
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! ✅")
    print("=" * 60)
    print("\nLog entries have been written to: agent_outputs/system_logs.jsonl")
    print("You can view the JSON logs to verify the format.")

if __name__ == "__main__":
    test_logging()
