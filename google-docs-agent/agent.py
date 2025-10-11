import os
from typing import Dict, Any
from functools import partial
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage
from tools import (
    _create_google_doc_impl,
    _add_text_to_doc_impl,
    _read_google_doc_impl,
)  # Import the implementation, not the decorated version
from dotenv import load_dotenv


def create_docs_agent(credentials_dict: Dict):

    # initialize the llm with gpt-4
    llm = ChatOpenAI(
        model="gpt-4", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # import tool decorator
    from langchain_core.tools import tool

    # create a wrapper tool with credentials already filled in
    # this uses a closure pattern - the inner function "remembers" credentials_dict
    @tool
    def create_doc(title: str) -> str:
        """Creates a new Google Doc and returns its ID and URL.

        Args:
            title: The name of the document (e.g., "Project Notes")
        """
        # call the implementation function with both title and credentials
        result = _create_google_doc_impl(title, credentials_dict)
        return result

    @tool
    def add_text(document_id: str, text: str) -> str:
        """Adds text to an existing Google Doc.

        Args:
            document_id: The ID of the document
            text: The text content to add
        """
        result = _add_text_to_doc_impl(document_id, text, credentials_dict)
        return result

    @tool
    def read_doc(document_id: str) -> str:
        """Reads text content from a Google Doc.

        Args:
            document_id: The ID of the document to read
        """
        result = _read_google_doc_impl(document_id, credentials_dict)
        return result

    # define the available tools for the agent
    tools = [create_doc, add_text, read_doc]

    # create the agent using langgraph's react pattern
    # model parameter is the llm, tools are the functions the agent can call
    agent = create_react_agent(model=llm, tools=tools)
    return agent


def main():
    """
    Test function - this is where we test our agent before using it in production
    """

    print("=" * 60)
    print("GOOGLE DOCS AGENT - Testing")
    print("=" * 60)
    print()

    # check for required environment variables
    required_vars = ["OPENAI_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print("Missing required environment variables:")
        for var in missing_vars:
            print(f" - {var}")
            print("Create a .env file with these variables")
            return

    test_credentials = {
        "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    }

    if (
        test_credentials["access_token"] is None
        or test_credentials["refresh_token"] is None
    ):
        print(
            "Missing Google OAuth tokens. Please set GOOGLE_ACCESS_TOKEN and GOOGLE_REFRESH_TOKEN in your environment."
        )
        return

    # step 3: try to run the agent
    try:
        print("🤖 Initializing Google Docs Agent...")
        agent = create_docs_agent(test_credentials)
        print("✅ Agent initialized successfully!\n")
        print("\n" + "=" * 60)
        print("TEST OPTIONS")
        print("=" * 60)
        print("What would you like to test?")
        print("1. Create a document only")
        print("2. Create and add text")
        print("3. Create, add text, and read back (full test)")
        print("4. Read an existing document")
        print("=" * 60)

        # step 4: collect user inputs
        choice = input("Enter your choice (1-4): ")

        if choice == "1":
            title = input("Enter document title: ")
            test_message = f"Create a document called '{title}'"

        elif choice == "2":
            title = input("Enter document title: ")
            text = input("Enter text to add: ")
            test_message = (
                f"Create a document called '{title}', then add this text: '{text}'"
            )

        elif choice == "3":
            title = input("Enter document title: ")
            text = input("Enter text to add: ")
            test_message = f"Create a document called '{title}', add the text '{text}', then read it back to me to confirm it worked."

        elif choice == "4":
            doc_id = input("Enter document ID: ")
            test_message = f"Read the document with ID: {doc_id}"

        else:
            print("Invalid choice. Using default test.")
            test_message = "Create a document called 'AI Agent Test', add the text 'This is a test!', then read it back."

        # step 5: invoke the agent with system message and user request
        # system message defines the agent's role and behavior
        system_prompt = """You are the Google Docs specialist agent for SafexpressOps.
Your only responsibility is creating and managing Google Docs.

When the supervisor agent routes a request to you:
1. Use the create_doc tool to create new documents
2. Use the add_text tool to add content to existing documents
3. Use the read_doc tool to read content from existing documents
4. Provide clear confirmation with the document URL
5. Report back to the supervisor with the result

Be concise and professional. Focus only on Google Docs tasks."""

        result = agent.invoke(
            {"messages": [("system", system_prompt), ("user", test_message)]}
        )

        # step 6: display the result
        print("\n" + "=" * 60)
        print("AGENT RESPONSE:")
        print("=" * 60)

        # langgraph returns a dict with 'messages' list
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
        # step 7: handle errors gracefully
        print(f"\n❌ Error: {e}")
        print(f"\n🐛 Error Type: {type(e).__name__}")
        print("\n🔧 Debugging Tips:")
        print("1. Check .env file has all variables (no quotes!)")
        print("2. Verify OpenAI API key is valid")
        print("3. Check if packages are installed: pip install -r requirements.txt")
        print("4. Make sure you're in virtual environment")

        import traceback

        print("\n📋 Full Error Details:")
        traceback.print_exc()


if __name__ == "__main__":
    # this runs when you execute: python agent.py
    # load environment variables first
    load_dotenv()

    # run the test
    main()
