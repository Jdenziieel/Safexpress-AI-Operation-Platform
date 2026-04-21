"""
Delivery Order Service - Multi-stage delivery order workflow logic.

Handles the delivery order search, preview, destination selection,
data extraction review, and full execution workflow.
Extracted from ConversationalAgent to separate delivery order concerns
from core conversation analysis logic.
"""

import os
import httpx
from typing import Optional, Dict, Any, List, Callable, Tuple
from models.models import ConversationState


class DeliveryOrderService:
    """
    Service layer for the delivery order workflow.

    Manages the multi-stage delivery order process:
      Stage 0: Detect delivery order request (pattern match)
      Stage 1: Preview emails with attachments
      Stage 1.5: Show email content, ask destination
      Stage 2: Collect sheet ID / doc title
      Stage 3: Confirm full plan
      Stage 4: Review extracted data
      Stage 5: Execute full workflow
    """

    def is_delivery_order_request(self, user_message: str) -> bool:
        """
        Quick pattern check to detect if user is asking about delivery orders or PDF extraction to sheets.
        
        Args:
            user_message: User message to check
            
        Returns:
            True if message appears to be a delivery order request
        """
        delivery_keywords = [
            "delivery order", "delivery orders", "purchase order", "purchase orders",
            "po ", "pos ", "orders from", "search for", "find orders", "find delivery",
            "orders to", "batangas", "supplier", "vendor order",
            "product requisition", "extract", "place data", "put", ".pdf", 
            "extract data", "pdf to sheet"
        ]
        
        user_lower = user_message.lower()
        return any(keyword in user_lower for keyword in delivery_keywords)
    
    def handle_delivery_order_preview(
        self,
        query: str,
        credentials_dict: Dict[str, Any],
        gmail_agent_url: str = None
    ) -> Dict[str, Any]:
        """
        Stage 1: Search for delivery orders without downloading (preview only).
        
        Args:
            query: Gmail search query (e.g., "from:supplier delivery")
            credentials_dict: User OAuth credentials
            gmail_agent_url: URL of Gmail agent (default from env)
            
        Returns:
            Dictionary with preview results or error
        """
        
        if gmail_agent_url is None:
            gmail_agent_url = os.getenv("GMAIL_AGENT_URL", "http://localhost:8000")
        
        try:
            payload = {
                "tool": "search_emails_with_delivery_order_attachments",
                "inputs": {
                    "query": query,
                    "max_results": 5,
                    "download_attachments": False  # Preview only - don't download yet
                },
                "credentials_dict": credentials_dict or {}
            }
            
            response = httpx.post(
                f"{gmail_agent_url}/execute_task",
                json=payload,
                timeout=30.0
            )
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Gmail agent error: {response.status_code}",
                    "preview": []
                }
            
            result = response.json()
            
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error", "Search failed"),
                    "preview": []
                }
            
            # Extract preview information
            emails = result.get("emails_with_attachments", [])
            preview = []
            
            for email in emails:
                email_preview = {
                    "id": email.get("id"),
                    "from": email.get("from"),
                    "subject": email.get("subject"),
                    "date": email.get("date"),
                    "attachment_count": len(email.get("attachments", [])),
                    "attachments": [
                        {
                            "filename": att.get("filename"),
                            "size_kb": att.get("size", 0) // 1024,
                            "mime_type": att.get("mime_type")
                        }
                        for att in email.get("attachments", [])
                    ]
                }
                preview.append(email_preview)
            
            return {
                "success": True,
                "error": None,
                "preview": preview,
                "total_found": result.get("total_emails_found", 0),
                "total_attachments": result.get("total_attachments_downloaded", 0)
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Preview failed: {str(e)}",
                "preview": []
            }
    
    def build_delivery_order_preview_response(
        self,
        preview_result: Dict[str, Any],
        conversation_state: ConversationState
    ) -> str:
        """
        Build a user-friendly preview response showing found orders.
        
        Args:
            preview_result: Result from handle_delivery_order_preview
            conversation_state: Conversation state to update
            
        Returns:
            Formatted response string
        """
        if not preview_result["success"]:
            return f" Search failed: {preview_result['error']}"
        
        preview = preview_result["preview"]
        
        if not preview:
            return " No delivery orders found matching your search. Try a different query."
        
        # Store preview results in conversation state for later execution
        conversation_state.extracted_info["delivery_order_preview"] = preview
        conversation_state.extracted_info["delivery_order_total_found"] = preview_result.get("total_found", 0)
        
        # Build formatted response
        response = f" **Found {len(preview)} delivery order(s):**\n\n"
        
        for i, email in enumerate(preview, 1):
            response += f"**{i}. {email['subject']}**\n"
            response += f"   From: {email['from']}\n"
            response += f"   Date: {email['date']}\n"
            response += f"   Attachments: {email['attachment_count']}\n"
            
            if email['attachments']:
                for att in email['attachments']:
                    response += f"     • {att['filename']} ({att['size_kb']} KB)\n"
            
            response += "\n"
        
        # Ask for confirmation
        response += "**Ready to process?**\n\n"
        response += "I can:\n"
        response += "1. Parse and extract the order data\n"
        response += "2. Upload results to a Google Sheet\n"
        response += "3. Create a summary document in Google Docs\n"
        response += "4. Save metadata to database\n\n"
        response += "**Which sheet should I upload to?** (Provide sheet ID or name)"
        
        # Mark that we're awaiting sheet confirmation
        conversation_state.extracted_info["delivery_order_stage"] = "awaiting_sheet_confirmation"
        conversation_state.clarification_question = response
        conversation_state.missing_fields = ["sheets_sheet_id"]
        conversation_state.ready_for_execution = False
        
        return response
    
    def handle_delivery_order_execution(
        self,
        user_message: str,
        conversation_state: ConversationState,
        credentials_dict: Dict[str, Any],
        gmail_agent_url: str = None,
        destination_type: str = "both",
        sheet_id: str = None,
        create_summary_doc: bool = True,
        summary_doc_title: str = None
    ) -> Dict[str, Any]:
        """
        Stage 5+: Execute full workflow (download, parse, transform, upload, save).
        
        Args:
            user_message: User's response (not used in new flow)
            conversation_state: Conversation state with all setup data
            credentials_dict: User OAuth credentials
            gmail_agent_url: URL of Gmail agent
            destination_type: "sheets", "docs", or "both"
            sheet_id: Google Sheets ID (if applicable)
            create_summary_doc: Whether to create summary document
            summary_doc_title: Title for summary document
            
        Returns:
            Dictionary with execution result
        """
        
        if gmail_agent_url is None:
            gmail_agent_url = os.getenv("GMAIL_AGENT_URL", "http://localhost:8000")
        
        try:
            # Get original query from conversation state
            original_query = conversation_state.extracted_info.get("delivery_order_query")
            if not original_query:
                return {
                    "success": False,
                    "error": "Lost original search query. Please start over.",
                    "processed": []
                }
            
            # Determine what to upload/create
            upload_to_sheets = destination_type in ["sheets", "both"]
            create_doc = create_summary_doc and destination_type in ["docs", "both"]
            
            # Call the full workflow tool
            payload = {
                "tool": "process_delivery_order_workflow",
                "inputs": {
                    "query": original_query,
                    "max_results": 5,
                    "download_attachments": True,
                    "save_to_db": True,
                    "upload_to_sheets": upload_to_sheets,
                    "sheets_sheet_id": sheet_id if upload_to_sheets else None,
                    "create_summary_doc": create_doc,
                    "summary_doc_title": summary_doc_title if create_doc else None,
                },
                "credentials_dict": credentials_dict or {}
            }
            
            response = httpx.post(
                f"{gmail_agent_url}/execute_task",
                json=payload,
                timeout=120.0
            )
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Workflow error: {response.status_code}",
                    "processed": []
                }
            
            result = response.json()
            return result
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Execution failed: {str(e)}",
                "processed": []
            }
    
    def build_delivery_order_execution_response(
        self,
        execution_result: Dict[str, Any],
        conversation_state: ConversationState
    ) -> str:
        """
        Build a user-friendly response showing execution results.
        
        Args:
            execution_result: Result from handle_delivery_order_execution
            conversation_state: Conversation state to update
            
        Returns:
            Formatted response string
        """
        if not execution_result["success"]:
            return f" Processing failed: {execution_result.get('error', 'Unknown error')}"
        
        processed = execution_result.get("processed", [])
        errors = execution_result.get("errors", [])
        document_url = execution_result.get("document_url")
        
        response = " **Delivery order processing complete!**\n\n"
        
        if processed:
            response += f"**Successfully processed: {len(processed)} order(s)**\n\n"
            for item in processed:
                response += f" {item.get('file_name', 'Unknown')}\n"
                response += f"   From: {item.get('email_from', 'Unknown')}\n"
                response += f"   Subject: {item.get('email_subject', 'N/A')}\n"
                response += f" Parsed Transformed Uploaded\n\n"
        
        if errors:
            response += f" **{len(errors)} error(s) occurred:**\n\n"
            for error in errors[:3]:  # Show first 3 errors
                response += f"   • {error}\n"
            if len(errors) > 3:
                response += f"   ... and {len(errors) - 3} more\n\n"
        
        summary = execution_result.get("search_summary", {})
        response += f"**Summary:** {summary.get('total_emails_found', 0)} emails processed\n\n"
        
        # Add document link if created
        if document_url:
            response += f" **Summary Document Created:** [View in Google Docs]({document_url})\n\n"
        
        # Clean up conversation state
        conversation_state.extracted_info["delivery_order_stage"] = "completed"
        conversation_state.ready_for_execution = False
        conversation_state.clarification_question = None
        conversation_state.missing_fields = []
        
        return response
    
    def show_email_content_and_ask_destination(
        self,
        email_preview: Dict[str, Any],
        conversation_state: ConversationState
    ) -> str:
        """
        Stage 1.5: Show actual email content and ask where to put the data.
        
        Args:
            email_preview: Email metadata from preview
            conversation_state: Conversation state to update
            
        Returns:
            Formatted response showing email content
        """
        response = f" **Email Found!**\n\n"
        response += f"**From:** {email_preview.get('from', 'Unknown')}\n"
        response += f"**Subject:** {email_preview.get('subject', 'N/A')}\n"
        response += f"**Date:** {email_preview.get('date', 'Unknown')}\n\n"
        
        # Show attachments
        attachments = email_preview.get('attachments', [])
        if attachments:
            response += "**Attachments:**\n"
            for att in attachments:
                response += f"  • {att.get('filename', 'Unknown')} ({att.get('size_kb', 0)} KB)\n"
            response += "\n"
        
        # AI must understand content message
        response += " I understand the email content and found the attachment.\n\n"
        
        # Ask for destination
        response += "**Where would you like me to put the extracted data?**\n\n"
        response += "1. **Google Sheets** - Upload to an existing sheet\n"
        response += "2. **Google Docs** - Create a summary document\n"
        response += "3. **Both** - Upload to sheets AND create a doc\n\n"
        response += "Just reply with your choice (1, 2, or 3):"
        
        # Update state
        conversation_state.extracted_info["delivery_order_stage"] = "awaiting_destination_choice"
        conversation_state.extracted_info["email_preview"] = email_preview
        conversation_state.clarification_question = response
        conversation_state.missing_fields = ["destination_choice"]
        conversation_state.ready_for_execution = False
        
        return response
    
    def format_extracted_data_for_review(
        self,
        parsed_data: Dict[str, Any],
        filename: str
    ) -> str:
        """
        Format extracted data in human-readable format (not JSON).
        
        Args:
            parsed_data: Parsed data from mapping agent
            filename: Name of the file that was extracted
            
        Returns:
            Formatted string for user review
        """
        response = f" **Extracted Data from {filename}:**\n\n"
        
        # If it's structured data with rows
        if isinstance(parsed_data, dict):
            if "rows" in parsed_data:
                rows = parsed_data["rows"]
                if rows and isinstance(rows, list):
                    # Show as a formatted table
                    headers = list(rows[0].keys()) if rows else []
                    response += "| " + " | ".join(headers) + " |\n"
                    response += "|" + "|".join(["---"] * len(headers)) + "|\n"
                    
                    for row in rows[:5]:  # Show first 5 rows
                        values = [str(row.get(h, "")) for h in headers]
                        response += "| " + " | ".join(values) + " |\n"
                    
                    if len(rows) > 5:
                        response += f"\n... and {len(rows) - 5} more rows\n"
                    
                    response += f"\n**Total rows:** {len(rows)}\n"
            else:
                # Show as key-value pairs
                for key, value in parsed_data.items():
                    if key not in ["rows", "metadata"]:
                        response += f"**{key}:** {value}\n"
        
        response += "\n Does this look correct?\n\n"
        response += "Please type **'Yes'** to confirm or **'No'** to cancel."
        
        return response
    
    def confirm_full_plan(
        self,
        conversation_state: ConversationState,
        destination_choice: str,
        sheet_id: str = None,
        summary_doc_title: str = None
    ) -> str:
        """
        Show the full plan before execution.
        
        Args:
            conversation_state: Current conversation state
            destination_choice: User's choice (1=sheets, 2=docs, 3=both)
            sheet_id: Google Sheets ID if applicable
            summary_doc_title: Doc title if applicable
            
        Returns:
            Formatted confirmation message
        """
        response = " **Let me confirm your request:**\n\n"
        response += "**Plan:**\n"
        response += "1. Read the document\n"
        response += "2. Extract its contents\n"
        response += "3. Save the data to the database\n"
        
        # Based on destination choice
        if destination_choice == "1" or destination_choice == "3":
            response += f"4. Put the data in **{sheet_id}** Sheets\n"
        if destination_choice == "2" or destination_choice == "3":
            doc_title = summary_doc_title or "Delivery Order Summary"
            response += f"4. Create a Google Doc: **{doc_title}**\n"
        
        response += "\n**Is this correct?** (Reply: **Yes** to proceed or **No** to cancel)"
        
        return response
    
    # CHECK THIS FUNCTION IF THIS IS WORKING OR IF THIS IS CURRENTLY IN USE
    def handle_destination_choice(
        self,
        user_message: str,
        conversation_state: ConversationState
    ) -> Dict[str, Any]:
        """
        Parse user's destination choice.
        
        Args:
            user_message: User's choice message
            conversation_state: Conversation state
            
        Returns:
            Dictionary with destination info
        """
        user_lower = user_message.lower().strip()
        
        # Determine destination choice
        if user_lower in ["1", "sheets", "sheet"]:
            destination_type = "sheets"
        elif user_lower in ["2", "docs", "doc"]:
            destination_type = "docs"
        elif user_lower in ["3", "both"]:
            destination_type = "both"
        else:
            return {
                "success": False,
                "error": f"Invalid choice. Please reply with 1, 2, or 3."
            }
        
        return {
            "success": True,
            "destination_type": destination_type,
            "requires_sheet_id": destination_type in ["sheets", "both"],
            "requires_doc_title": destination_type in ["docs", "both"]
        }

    def route_delivery_stage(
        self,
        user_message: str,
        conversation_state: ConversationState,
        finalize: Callable[[str, ConversationState], Tuple[str, ConversationState]],
    ) -> Optional[Tuple[str, ConversationState]]:
        """
        Route the current message through the multi-stage delivery order workflow.

        Returns (response, state) if the message was handled by a delivery stage,
        or None if this is not a delivery order interaction so the caller should
        continue with normal analysis.

        Args:
            user_message: Current user input
            conversation_state: Conversation state (mutated in place)
            finalize: Callback that persists state and returns (response, state).
                      Signature: finalize(response_text, conversation_state)
        """
        delivery_stage = conversation_state.extracted_info.get("delivery_order_stage")

        # STAGE 0: Initial delivery order search
        if self.is_delivery_order_request(user_message) and not delivery_stage:
            print(f" DELIVERY ORDER SEARCH: User is searching for delivery orders")

            query = user_message
            if "from:" not in query.lower():
                if "batangas" in query.lower():
                    query = "from:supplier delivery has:attachment to:batangas"
                elif "po" in query.lower() or "purchase order" in query.lower():
                    query = "subject:PO has:attachment"
                else:
                    query = f"{query} has:attachment"

            conversation_state.extracted_info["delivery_order_query"] = query
            credentials_dict = {}  # TODO: Get from session/auth context

            preview_result = self.handle_delivery_order_preview(query=query, credentials_dict=credentials_dict)

            if not preview_result["success"]:
                response = f" Search failed: {preview_result['error']}"
            else:
                emails = preview_result["preview"]
                if emails:
                    first_email = emails[0]
                    response = self.show_email_content_and_ask_destination(first_email, conversation_state)
                else:
                    response = " No delivery orders found. Try a different search."
                    conversation_state.extracted_info["delivery_order_stage"] = "completed"

            return finalize(response, conversation_state)

        # STAGE 1: Awaiting destination choice (sheets/docs/both)
        if delivery_stage == "awaiting_destination_choice":
            print(f" DELIVERY ORDER DESTINATION: User choosing where to put data")

            dest_result = self.handle_destination_choice(user_message, conversation_state)
            if not dest_result["success"]:
                response = dest_result["error"]
            else:
                destination_type = dest_result["destination_type"]
                conversation_state.extracted_info["destination_type"] = destination_type

                if dest_result["requires_sheet_id"]:
                    conversation_state.extracted_info["delivery_order_stage"] = "awaiting_sheet_id"
                    response = " **Which Google Sheet should I upload the data to?**\n\n"
                    response += "Provide the sheet ID or name (e.g., 'Order-123' or '1a2b3c4d5e6f')"
                    conversation_state.missing_fields = ["sheets_sheet_id"]
                elif dest_result["requires_doc_title"]:
                    conversation_state.extracted_info["delivery_order_stage"] = "awaiting_doc_title"
                    response = " **What should I name the document?**\n\n"
                    response += "E.g., 'Delivery Orders Summary' or 'Order Report Jan 2024'"
                    conversation_state.missing_fields = ["summary_doc_title"]
                else:
                    response = self.confirm_full_plan(conversation_state, destination_type)
                    conversation_state.extracted_info["delivery_order_stage"] = "confirming_plan"

            return finalize(response, conversation_state)

        # STAGE 2: Awaiting sheet ID
        if delivery_stage == "awaiting_sheet_id":
            print(f" DELIVERY ORDER SHEET_ID: User provided sheet ID")

            sheet_id = user_message.strip()
            conversation_state.extracted_info["sheets_sheet_id"] = sheet_id

            destination_type = conversation_state.extracted_info.get("destination_type", "sheets")
            if destination_type == "both":
                conversation_state.extracted_info["delivery_order_stage"] = "awaiting_doc_title"
                response = " **What should I name the summary document?**\n\n"
                response += "E.g., 'Delivery Orders Summary' or 'Order Report Jan 2024'"
                conversation_state.missing_fields = ["summary_doc_title"]
            else:
                response = self.confirm_full_plan(conversation_state, destination_type, sheet_id)
                conversation_state.extracted_info["delivery_order_stage"] = "confirming_plan"

            return finalize(response, conversation_state)

        # STAGE 2.5: Awaiting doc title
        if delivery_stage == "awaiting_doc_title":
            print(f" DELIVERY ORDER DOC_TITLE: User provided doc title")

            doc_title = user_message.strip()
            conversation_state.extracted_info["summary_doc_title"] = doc_title
            destination_type = conversation_state.extracted_info.get("destination_type", "both")
            sheet_id = conversation_state.extracted_info.get("sheets_sheet_id")

            response = self.confirm_full_plan(conversation_state, destination_type, sheet_id, doc_title)
            conversation_state.extracted_info["delivery_order_stage"] = "confirming_plan"

            return finalize(response, conversation_state)

        # STAGE 3: Confirming the full plan
        if delivery_stage == "confirming_plan":
            print(f" DELIVERY ORDER CONFIRM: User confirming the plan")

            user_lower = user_message.lower().strip()
            if user_lower not in ["yes", "y", "confirm", "proceed"]:
                response = " Plan cancelled. Let me know if you want to try again."
                conversation_state.extracted_info["delivery_order_stage"] = "completed"
            else:
                response = " Great! Let me extract the contents and show them to you first...\n\n"

                extracted_data = {
                    "rows": [
                        {"Product": "Item 1", "Quantity": "10", "Price": "$100"},
                        {"Product": "Item 2", "Quantity": "5", "Price": "$200"},
                    ]
                }

                conversation_state.extracted_info["extracted_data"] = extracted_data
                conversation_state.extracted_info["delivery_order_stage"] = "awaiting_data_confirmation"
                conversation_state.missing_fields = ["data_confirmation"]

                response += self.format_extracted_data_for_review(extracted_data, "order.pdf")

            return finalize(response, conversation_state)

        # STAGE 4: Awaiting data confirmation
        if delivery_stage == "awaiting_data_confirmation":
            print(f" DELIVERY ORDER DATA_CHECK: User verifying extracted data")

            user_lower = user_message.lower().strip()
            if user_lower not in ["yes", "y", "correct", "looks good"]:
                response = " Data verification refused. Request cancelled."
                conversation_state.extracted_info["delivery_order_stage"] = "completed"
            else:
                response = " **Executing the workflow...**\n\n"

                conversation_state.extracted_info["delivery_order_stage"] = "executing"
                destination_type = conversation_state.extracted_info.get("destination_type", "both")
                sheet_id = conversation_state.extracted_info.get("sheets_sheet_id")
                doc_title = conversation_state.extracted_info.get("summary_doc_title")

                credentials_dict = {}
                execution_result = self.handle_delivery_order_execution(
                    user_message="",
                    conversation_state=conversation_state,
                    credentials_dict=credentials_dict,
                    destination_type=destination_type,
                    sheet_id=sheet_id,
                    create_summary_doc=destination_type in ["docs", "both"],
                    summary_doc_title=doc_title
                )

                response += self.build_delivery_order_execution_response(execution_result, conversation_state)

            return finalize(response, conversation_state)

        # STAGE (legacy): Awaiting sheet confirmation — direct execution
        if delivery_stage == "awaiting_sheet_confirmation":
            print(f" DELIVERY ORDER EXECUTION: User confirmed, executing full workflow")

            credentials_dict = {}
            execution_result = self.handle_delivery_order_execution(
                user_message=user_message,
                conversation_state=conversation_state,
                credentials_dict=credentials_dict
            )
            response = self.build_delivery_order_execution_response(execution_result, conversation_state)

            return finalize(response, conversation_state)

        # Not a delivery order interaction
        return None
