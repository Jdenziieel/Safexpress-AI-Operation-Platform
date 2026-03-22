from agent_capabilities_v3 import agent_capabilities

# Check if docs_agent has the right tools
print("DOCS_AGENT tools:")
for tool_name in agent_capabilities["docs_agent"]["tools"].keys():
    print(f"  - {tool_name}")

print("\nSHEETS_AGENT tools:")
for tool_name in agent_capabilities["sheets_agent"]["tools"].keys():
    print(f"  - {tool_name}")

# Check if sheets tools are leaking into docs
docs_tools = set(agent_capabilities["docs_agent"]["tools"].keys())
sheets_tools = set(agent_capabilities["sheets_agent"]["tools"].keys())
leaked = docs_tools & sheets_tools
if leaked:
    print(f"\n❌ BUG! These sheets tools are in docs_agent: {leaked}")
else:
    print("\n✅ No tool leakage!")