import os
import json
from typing import Dict, Any
from functools import partial
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage
from tools import (
    _create_from_reference_impl,
    _list_user_docs_impl,
    _extract_template_structure_impl,
    _create_google_doc_impl,
    _add_text_to_doc_impl,
    _read_google_doc_impl,
    _share_google_docs_impl,
    _edit_google_doc_impl,
    _update_entire_doc_impl,
    _create_doc_with_content_impl,
    _add_text_from_file_impl,
)
from dotenv import load_dotenv


def create_docs_agent(credentials_dict: Dict):

    # initialize the llm with gpt-4
    llm = ChatOpenAI(
        model="gpt-4", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # import tool decorator
    from langchain_core.tools import tool

    @tool
    def list_my_docs(search_query: str = "") -> str:
        """Lists your Google Docs to find templates.

        Args:
            search_query: Optional search term (e.g., "template", "MOM", "minutes")

        Use this when user wants to:
        - Find their template documents
        - See what documents they have
        - Search for a specific template

        Example: list_my_docs("meeting template")
        """
        result = _list_user_docs_impl(credentials_dict, search_query)
        return result

    @tool
    def extract_template_format(template_document_id: str) -> str:
        """Analyzes a document to extract its formatting and structure.

        Args:
            template_document_id: The ID of the template document

        This extracts:
        - Font styles (bold, italic, sizes, font families)
        - Heading styles
        - Placeholders like [DATE], [NAME], etc.
        - Table structures

        Use this when user wants to:
        - Use their own document as a template
        - See what placeholders are in a template
        - Understand the structure of a reference document

        Example: extract_template_format("1abc123xyz")
        """
        result = _extract_template_structure_impl(
            template_document_id, credentials_dict
        )
        return result

    @tool
    def create_from_my_template(
        template_document_id: str, new_title: str, placeholders: str = ""
    ) -> str:
        """Creates a new document using YOUR template document as reference.

        Args:
            template_document_id: ID of your template document
            new_title: Title for the new document
            placeholders: JSON string of placeholder values
                Format: '{"DATE": "Jan 15, 2025", "VENUE": "Room A"}'

        This will:
        1. Copy the formatting from your template
        2. Replace placeholders with your values
        3. Create a new formatted document

        Use this when user wants to:
        - Create document from their own template
        - Fill in meeting minutes from their format
        - Replicate their custom document style

        Example:
        create_from_my_template(
            "1abc123xyz",
            "Team Meeting - Jan 15",
            '{"DATE": "January 15, 2025", "TIME": "2:00 PM"}'
        )
        """
        import json

        # Parse placeholder values
        placeholder_values = {}
        if placeholders:
            try:
                placeholder_values = json.loads(placeholders)
            except:
                pass

        result = _create_from_reference_impl(
            template_document_id, new_title, placeholder_values, credentials_dict
        )
        return result

    # create a wrapper tool with credentials already filled in
    @tool
    def create_doc(title: str) -> str:
        """Creates a new Google Doc and returns its ID and URL.

        Args:
            title: The name of the document (e.g., "Project Notes")
        """
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

    @tool
    def share_doc(document_id: str, email: str, role: str = "reader") -> str:
        """Shares a Google Doc with a specified email address.

        Args:
            document_id: The ID of the document to share
            email: The email address to share the document with
            role: The access role ("reader", "commenter", "writer")
        """
        result = _share_google_docs_impl(document_id, email, role, credentials_dict)
        return result

    # NEW: Edit/replace specific text in document
    @tool
    def edit_doc(document_id: str, old_text: str, new_text: str) -> str:
        """Edits/replaces specific text in a Google Doc.

        Args:
            document_id: The ID of the document to edit
            old_text: The text to find and replace
            new_text: The replacement text
        """
        result = _edit_google_doc_impl(
            document_id, old_text, new_text, credentials_dict
        )
        return result

    # NEW: Update entire document content
    @tool
    def update_doc(document_id: str, new_content: str) -> str:
        """Replaces the entire content of a Google Doc with new content.

        Args:
            document_id: The ID of the document to update
            new_content: The new complete content for the document
        """
        result = _update_entire_doc_impl(document_id, new_content, credentials_dict)
        return result

    @tool
    def create_doc_with_content(title: str, text: str = "", file_path: str = "") -> str:
        """Creates a new Google Doc and populates it with content in one step.

        Args:
            title: The name of the document
            text: Text content to add (optional if file_path given)
            file_path: Local file path to read content from (optional if text given)
        """
        result = _create_doc_with_content_impl(
            title=title,
            credentials_dict=credentials_dict,
            text=text or None,
            file_path=file_path or None,
        )
        return json.dumps(result)

    @tool
    def add_text_from_file(document_id: str, file_path: str) -> str:
        """Reads a local file and adds its content to an existing Google Doc.

        Args:
            document_id: The ID of the document
            file_path: Local file path to read (PDF, txt, etc.)
        """
        result = _add_text_from_file_impl(
            document_id=document_id,
            file_path=file_path,
            credentials_dict=credentials_dict,
        )
        return json.dumps(result)

    tools = [
        list_my_docs,
        extract_template_format,
        create_from_my_template,
        create_doc,
        add_text,
        read_doc,
        share_doc,
        edit_doc,
        update_doc,
        create_doc_with_content,
        add_text_from_file,
    ]

    # create the agent using langgraph's react pattern
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
        print("5. Share an existing document")
        print("6. Edit text in a document (find and replace)")  # NEW
        print("7. Update entire document content")  # NEW
        print("=" * 60)

        choice = input("Enter your choice (1-7): ")

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

        elif choice == "5":
            doc_id = input("Enter document ID: ")
            email = input("Enter email address to share with: ")
            role = (
                input("Enter role (reader/writer/commenter) [default: reader]: ")
                or "reader"
            )
            test_message = f"Share the document with ID {doc_id} with {email} as {role}"

        # NEW: Edit text option
        elif choice == "6":
            doc_id = input("Enter document ID: ")
            old_text = input("Enter text to find: ")
            new_text = input("Enter replacement text: ")
            test_message = (
                f"In document {doc_id}, replace '{old_text}' with '{new_text}'"
            )

        # NEW: Update entire document option
        elif choice == "7":
            doc_id = input("Enter document ID: ")
            new_content = input("Enter new content for the document: ")
            test_message = (
                f"Update document {doc_id} with this new content: '{new_content}'"
            )

        else:
            print("Invalid choice. Using default test.")
            test_message = "Create a document called 'AI Agent Test', add the text 'This is a test!', then read it back."

        system_prompt = """You are the Google Docs specialist agent for SafexpressOps.
Your only responsibility is creating and managing Google Docs.

When the supervisor agent routes a request to you:
1. Use create_doc to create new documents
2. Use add_text to add content to documents
3. Use read_doc to read content from documents
4. Use edit_doc to find and replace specific text
5. Use update_doc to replace entire document content
6. Use share_doc to share documents with users
7. Provide clear confirmation with the document URL
8. Report back to the supervisor with the result

Be concise and professional. Focus only on Google Docs tasks."""

        result = agent.invoke(
            {"messages": [("system", system_prompt), ("user", test_message)]}
        )

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
    load_dotenv()
    main()
