import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from tools import (
    _search_emails_impl,
    _send_email_impl,
    _send_email_with_attachments_impl,
    _reply_to_email_impl,
    _forward_email_impl,
    _create_draft_email_impl,
    _send_draft_email_impl,
    _get_thread_conversation_impl,
    _add_label_impl,
    _remove_label_impl,
    _download_attachment_impl,
)

from dotenv import load_dotenv


def create_email_agent(credentials_dict: Dict):
    # initialize the llm with gpt-4o (128k context window)
    # gpt-4o has 128,000 token context vs gpt-4's 8,192 tokens
    llm = ChatOpenAI(
        model="gpt-4o", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # import tool decorator
    from langchain_core.tools import tool

    # create wrapper tool with credentials already filled in
    @tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Sends an email using Gmail API.
        
        DEPRECATED: This function sends emails immediately without review.
        Consider using create_draft_email + send_draft_email for safer workflow.

        Args:
            to: Recipient email address
            subject: Subject of the email
            body: Body content of the email
        """
        result = _send_email_impl(to, subject, body, credentials_dict)
        return result

    @tool
    def create_draft_email(to: str, subject: str, body: str) -> str:
        """Creates a draft email using Gmail API.

        Args:
            to: Recipient email address
            subject: Subject of the email
            body: Body content of the email
        """
        result = _create_draft_email_impl(to, subject, body, credentials_dict)
        return result
    
    @tool
    def send_draft_email(draft_id: str) -> str:
        """Sends a draft email using Gmail API.

        Args:
            draft_id: The ID of the draft email to send
        """
        result = _send_draft_email_impl(draft_id, credentials_dict)
        return result

    # @tool
    # def read_recent_emails(max_results: int) -> str:
    #     """Reads recent emails from Gmail.

    #     Args:
    #         max_results: Number of recent emails to fetch
    #     """
    #     return _read_recent_emails_impl(max_results, credentials_dict)

    @tool
    def search_emails(query: str, max_results: int) -> str:
        """Search emails in Gmail matching a query.

        Args:
            query: Search query string (e.g., "from:example@example.com")
            max_results: Number of emails to fetch
        """
        return _search_emails_impl(query, max_results, credentials_dict)

    @tool
    def send_email_with_attachment(
        to: str, subject: str, body: str, file_path: str
    ) -> str:
        """Sends an email with an attachment using Gmail API.

        Args:
            to: Recipient email address
            subject: Subject of the email
            body: Body content of the email
            file_path: Path to the file to attach
        """
        result = _send_email_with_attachments_impl(
            to, subject, body, file_path, credentials_dict
        )
        return result

    @tool
    def reply_to_email(message_id: str, reply_body: str) -> str:
        """Replies to a specific email using Gmail API.

        Args:
            message_id: The ID of the email message to reply to
            reply_body: The reply message content
        """
        result = _reply_to_email_impl(message_id, reply_body, credentials_dict)
        return result

    @tool
    def forward_email(message_id: str, to: str, forward_message: str = "") -> str:
        """Forwards an email to another recipient using Gmail API.

        Args:
            message_id: The ID of the email message to forward
            to: Recipient email address to forward to
            forward_message: Optional message to add before the forwarded content
        """
        result = _forward_email_impl(message_id, to, forward_message, credentials_dict)
        return result

    @tool
    def get_thread_conversation(thread_id: str) -> str:
        """Gets all messages in an email thread/conversation.

        Args:
            thread_id: The thread ID from search_emails or read_recent_emails
        """
        return _get_thread_conversation_impl(thread_id, credentials_dict)

    @tool
    def add_label(message_id: str, label: str) -> str:
        """Adds a system label to an email (star, mark unread, mark important, spam, trash).

        Args:
            message_id: The message ID of the email to label
            label: Label to add - STARRED, UNREAD, IMPORTANT, SPAM, or TRASH
        """
        return _add_label_impl(message_id, label, credentials_dict)

    @tool
    def remove_label(message_id: str, label: str) -> str:
        """Removes a system label from an email (unstar, mark read, unmark important, remove from spam/trash).

        Args:
            message_id: The message ID of the email to unlabel
            label: Label to remove - STARRED, UNREAD, IMPORTANT, SPAM, or TRASH
        """
        return _remove_label_impl(message_id, label, credentials_dict)

    @tool
    def download_attachment(message_id: str, attachment_id: str, save_path: str) -> str:
        """Downloads an email attachment to local storage.

        Args:
            message_id: The message ID containing the attachment
            attachment_id: The attachment ID from email details
            save_path: Absolute path where the file should be saved
        """
        return _download_attachment_impl(message_id, attachment_id, save_path, credentials_dict)

    tools = [
        send_email,
        create_draft_email,
        send_draft_email,
        search_emails,
        send_email_with_attachment,
        reply_to_email,
        forward_email,
        get_thread_conversation,
        add_label,
        remove_label,
        download_attachment,
    ]

    # Create agent with recursion limit to prevent timeout
    # recursion_limit controls max steps the agent can take
    agent = create_react_agent(model=llm, tools=tools)
    return agent
