"""
Google Docs Agent Creator - Lambda Compatible Version
"""

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from tools import (
    _create_google_doc_impl,
    _add_text_to_doc_impl,
    _read_google_doc_impl,
    _share_google_docs_impl,
)


def create_docs_agent(credentials_dict: dict, openai_api_key: str = None):
    """
    Create Google Docs agent with tools

    Args:
        credentials_dict: Google OAuth credentials
        openai_api_key: OpenAI API key (required in Lambda)
    """

    if not openai_api_key:
        raise ValueError("openai_api_key is required for Lambda deployment")

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=openai_api_key)

    @tool
    def create_doc(title: str) -> str:
        """Creates a new Google Doc and returns its ID and URL.
        Args:
            title: The name of the document
        """
        return _create_google_doc_impl(title, credentials_dict)

    @tool
    def add_text(document_id: str, text: str) -> str:
        """Adds text to an existing Google Doc.
        Args:
            document_id: The ID of the document
            text: The text content to add
        """
        return _add_text_to_doc_impl(document_id, text, credentials_dict)

    @tool
    def read_doc(document_id: str) -> str:
        """Reads text content from a Google Doc.
        Args:
            document_id: The ID of the document to read
        """
        return _read_google_doc_impl(document_id, credentials_dict)

    @tool
    def share_doc(document_id: str, email: str, role: str = "reader") -> str:
        """Shares a Google Doc with a specified email address.
        Args:
            document_id: The ID of the document to share
            email: The email address to share with
            role: The access role (reader, commenter, writer)
        """
        return _share_google_docs_impl(document_id, email, role, credentials_dict)

    tools = [create_doc, add_text, read_doc, share_doc]
    agent = create_react_agent(model=llm, tools=tools)

    return agent
