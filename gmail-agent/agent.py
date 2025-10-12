import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from tools import (
    _send_email_impl,
)

from dotenv import load_dotenv


def create_email_agent(credentials_dict: Dict):
    # initialize the llm with gpt-4
    llm = ChatOpenAI(
        model="gpt-4", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # import tool decorator
    from langchain_core.tools import tool

    # create wrapper tool with credentials already filled in
    @tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Sends an email using Gmail API.

        Args:
            to: Recipient email address
            subject: Subject of the email
            body: Body content of the email
        """
        result = _send_email_impl(to, subject, body, credentials_dict)
        return result

    tools = [send_email]

    agent = create_react_agent(model=llm, tools=tools)
    return agent


def main():
    """Test function for gmail agent"""

    print("=" * 60)
    print("GMAIL AGENT - Testing")
    print("=" * 60)
    print()

    # check for required environment variables
    required_vars = ["OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print("Missing required environment variables:")
        for var in missing_vars:
            print(f" - {var}")
            return

    # setup credentials
    test_credentials = {
        "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    }

    if not test_credentials["access_token"] or not test_credentials["refresh_token"]:
        print("Missing Google OAuth tokens.")
        return

    # initialize agent'
    try:
        print("🤖 Initializing Gmail Agent...")
        agent = create_email_agent(test_credentials)
        print("✅ Agent initialized successfully!\n")

        # Test menu (add after you have tools working)
        print("\n" + "=" * 60)
        print("TEST OPTIONS")
        print("=" * 60)
        print("1. Send a test email")
        print("2. Read recent emails")
        print("=" * 60)

        choice = input("\nEnter your choice (1-2): ")

        if choice == "1":
            to = input("Send to (email): ")
            subject = input("Subject: ")
            body = input("Body: ")
            test_message = (
                f"Send an email to {to} with subject '{subject}' and body: {body}"
            )

        elif choice == "2":
            test_message = "Show me my 5 most recent emails"

        else:
            print("Invalid choice.")
            return

        # system prompt for Gmail agent
        system_prompt = """
            You are the Gmail specialist Agent for SafexpressOps
            Your only responsibility is sending and managing emails.

            When the Supervisor agent routes a request to you,
            1. Use send_email to send emails
            2. use read_recent_emails to read recent emails
            3. use search_emails to find specific emails
            4. Provide clear confirmation of actions taken

            Be concise and professional. Only focus on Gmail tasks.
            """

        # invoke agent
        result = agent.invoke(
            {"messages": [("system", system_prompt), ("user", test_message)]}
        )

        # display result
        print("\n" + "=" * 60)
        print("AGENT RESPONSE:")
        print("=" * 60)

        messages = result.get("messages", [])
        if messages:
            final_message = messages[-1]
            print(f"\n{final_message.content}\n")
        else:
            print(result)

        print("=" * 60)
        print("✅ Test completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    load_dotenv()
    main()
