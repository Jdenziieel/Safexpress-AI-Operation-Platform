"""
Test the updated _build_capabilities_summary with can_be_derived_from metadata
"""
import sys
import os
sys.path.append('.')

from conversational_agent import ConversationalAgent

# Initialize agent with API key from environment
api_key = os.getenv("OPENAI_API_KEY", "dummy-key-for-testing")
agent = ConversationalAgent(openai_api_key=api_key)

# Test with specific agents
agent_list = ['gmail_agent', 'calendar_agent', 'docs_agent', 'sheets_agent']

print("🔍 Testing updated _build_capabilities_summary with can_be_derived_from metadata\n")
print("=" * 80)

capabilities_output = agent._build_capabilities_summary(agent_list)

print(capabilities_output)

print("\n" + "=" * 80)
print("\n✅ Legend:")
print("  • [↗source_tool: criteria] = This argument can be derived from source_tool using these search criteria")
print("\n📋 Example Interpretation:")
print("  • forward_email(message_id [↗search_emails: sender_email, subject_keywords, date_range, email_description], to, [forward_message])")
print("    ↳ message_id can be found by first calling search_emails with sender_email OR subject_keywords")
