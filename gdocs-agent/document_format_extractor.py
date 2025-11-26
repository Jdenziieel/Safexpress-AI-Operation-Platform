"""
document_format_extractor.py
Extract formatting and structure from a reference Google Doc
This allows users to upload their own templates!
"""

import os
from typing import Dict, List, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def get_google_service(service_name: str, version: str, credentials_dict: Dict):
    """Get Google API service"""
    creds = Credentials(
        token=credentials_dict["access_token"],
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    service = build(service_name, version, credentials=creds)
    return service


class DocumentFormatExtractor:
    """Extract formatting information from a reference document"""

    def __init__(self, credentials_dict: Dict):
        self.credentials_dict = credentials_dict
        self.docs_service = get_google_service("docs", "v1", credentials_dict)
        self.drive_service = get_google_service("drive", "v3", credentials_dict)

    def extract_document_structure(self, document_id: str) -> Dict:
        """
        Extract complete structure and formatting from a reference document

        Args:
            document_id: ID of the reference document

        Returns:
            Dict with structure, styles, and content placeholders
        """
        try:
            # Get the document
            document = (
                self.docs_service.documents().get(documentId=document_id).execute()
            )

            structure = {
                "title": document.get("title"),
                "document_id": document_id,
                "styles": [],
                "content_blocks": [],
                "placeholders": [],
            }

            # Extract content and styles
            content = document.get("body", {}).get("content", [])

            for element in content:
                if "paragraph" in element:
                    block = self._extract_paragraph_info(element["paragraph"])
                    structure["content_blocks"].append(block)

                elif "table" in element:
                    block = self._extract_table_info(element["table"])
                    structure["content_blocks"].append(block)

            return structure

        except HttpError as error:
            return {"error": f"Error extracting document: {error}"}

    def _extract_paragraph_info(self, paragraph: Dict) -> Dict:
        """Extract paragraph formatting and content"""
        block = {"type": "paragraph", "style": {}, "text": "", "elements": []}

        # Get paragraph style
        para_style = paragraph.get("paragraphStyle", {})
        block["style"]["alignment"] = para_style.get("alignment", "START")
        block["style"]["heading"] = para_style.get("namedStyleType", "NORMAL_TEXT")
        block["style"]["indent_start"] = para_style.get("indentStart", {}).get(
            "magnitude", 0
        )
        block["style"]["line_spacing"] = para_style.get("lineSpacing", 100)

        # Get text elements and their styles
        elements = paragraph.get("elements", [])
        for element in elements:
            if "textRun" in element:
                text_run = element["textRun"]
                text_content = text_run.get("content", "")
                text_style = text_run.get("textStyle", {})

                element_info = {
                    "text": text_content,
                    "style": {
                        "bold": text_style.get("bold", False),
                        "italic": text_style.get("italic", False),
                        "underline": text_style.get("underline", False),
                        "font_family": text_style.get("weightedFontFamily", {}).get(
                            "fontFamily", "Arial"
                        ),
                        "font_size": text_style.get("fontSize", {}).get(
                            "magnitude", 11
                        ),
                        "foreground_color": text_style.get("foregroundColor", {}),
                    },
                }

                block["elements"].append(element_info)
                block["text"] += text_content

        return block

    def _extract_table_info(self, table: Dict) -> Dict:
        """Extract table structure and formatting"""
        block = {
            "type": "table",
            "rows": table.get("rows", 0),
            "columns": table.get("columns", 0),
            "cells": [],
        }

        # Extract cell information
        table_rows = table.get("tableRows", [])
        for row in table_rows:
            row_cells = []
            cells = row.get("tableCells", [])
            for cell in cells:
                cell_info = {"content": [], "style": cell.get("tableCellStyle", {})}
                # Extract content from each cell
                cell_content = cell.get("content", [])
                for element in cell_content:
                    if "paragraph" in element:
                        para_info = self._extract_paragraph_info(element["paragraph"])
                        cell_info["content"].append(para_info)
                row_cells.append(cell_info)
            block["cells"].append(row_cells)

        return block

def identify_placeholders(self, structure: Dict) -> List[str]:
    """
    Identify placeholder text in multiple formats:
    1. Bracketed: [DATE], [NAME], {PLACEHOLDER}
    2. Blank lines: date:____, attendees: ____, name:_____
    
    Args:
        structure: Document structure from extract_document_structure
    
    Returns:
        List of unique placeholders found
    """
    placeholders = set()
    import re
    
    # Pattern 1: Match [PLACEHOLDER] or {PLACEHOLDER}
    bracket_pattern = r"\[(.*?)\]|\{(.*?)\}"
    
    # Pattern 2: Match key:____ or key: ____ (blank line format)
    blank_line_pattern = r'([a-zA-Z\s]+):\s*_{2,}'
    
    for block in structure.get("content_blocks", []):
        text = block.get("text", "")
        
        # Find bracketed placeholders
        bracket_matches = re.findall(bracket_pattern, text)
        for match in bracket_matches:
            # match is tuple of (bracket_content, brace_content)
            placeholder = match[0] if match[0] else match[1]
            if placeholder:
                placeholders.add(placeholder.upper())  # Normalize to uppercase
        
        # Find blank line placeholders (NEW!)
        blank_matches = re.findall(blank_line_pattern, text, re.IGNORECASE)
        for match in blank_matches:
            # Normalize: "date" → "DATE", "Company Name" → "COMPANY_NAME"
            normalized = match.strip().upper().replace(' ', '_')
            placeholders.add(normalized)
            print(f"  🔍 Detected blank line placeholder: '{match}:____' → [{normalized}]")
    
    result = sorted(list(placeholders))
    print(f"📋 Total placeholders found: {result}")
    return result

    def create_from_template(
        self,
        template_document_id: str,
        new_title: str,
        placeholder_values: Dict[str, str] = None,
    ) -> str:
        """
        Create a new document based on a template document

        Args:
            template_document_id: ID of template document
            new_title: Title for new document
            placeholder_values: Dict mapping placeholders to values
                Example: {"DATE": "January 15, 2025", "NAME": "John Doe"}

        Returns:
            New document ID and URL
        """
        try:
            # Step 1: Extract template structure
            print("📋 Extracting template structure...")
            structure = self.extract_document_structure(template_document_id)

            # Step 2: Create new blank document
            print("📄 Creating new document...")
            doc = {"title": new_title}
            new_doc = self.docs_service.documents().create(body=doc).execute()
            new_doc_id = new_doc.get("documentId")

            # Step 3: Replicate structure in new document
            print("🎨 Applying formatting...")
            self._replicate_structure(new_doc_id, structure, placeholder_values)

            doc_url = f"https://docs.google.com/document/d/{new_doc_id}/edit"

            return {
                "success": True,
                "document_id": new_doc_id,
                "url": doc_url,
                "title": new_title,
                "template_used": structure.get("title"),
            }

        except Exception as error:
            return {"success": False, "error": str(error)}

    def _replicate_structure(
        self,
        new_doc_id: str,
        structure: Dict,
        placeholder_values: Dict[str, str] = None,
    ):
        """Replicate document structure with formatting in new document"""

        requests = []
        current_index = 1  # Start at index 1 (after title)

        placeholder_values = placeholder_values or {}

        # Smart key normalization (already in your code - keep this!)
        normalized_values = {}
        for key, value in placeholder_values.items():
            normalized_key = key.upper().replace(" ", "_")
            normalized_values[normalized_key] = value
            normalized_values[key] = value
        placeholder_values = normalized_values

        for block in structure.get("content_blocks", []):
            if block["type"] == "paragraph":
                # Store original text before replacement
                original_text = block["text"]
                replaced_text = original_text

                # Replace placeholders
                for placeholder, value in placeholder_values.items():
                    replaced_text = replaced_text.replace(f"[{placeholder}]", value)
                    replaced_text = replaced_text.replace(f"{{{placeholder}}}", value)

                # Insert text
                requests.append(
                    {
                        "insertText": {
                            "location": {"index": current_index},
                            "text": replaced_text,
                        }
                    }
                )

                end_index = current_index + len(replaced_text)

                # Apply paragraph style (headings, alignment)
                if block["style"].get("heading") != "NORMAL_TEXT":
                    requests.append(
                        {
                            "updateParagraphStyle": {
                                "range": {
                                    "startIndex": current_index,
                                    "endIndex": end_index,
                                },
                                "paragraphStyle": {
                                    "namedStyleType": block["style"]["heading"],
                                    "alignment": block["style"].get(
                                        "alignment", "START"
                                    ),
                                },
                                "fields": "namedStyleType,alignment",
                            }
                        }
                    )

                # Apply text formatting intelligently
                text_was_replaced = original_text != replaced_text

                if text_was_replaced and block["elements"]:
                    # Text was modified - apply uniform formatting using first element's style
                    # This avoids index errors while keeping the template's base formatting
                    first_style = block["elements"][0]["style"]
                    text_style = {}
                    fields = []

                    if first_style.get("bold"):
                        text_style["bold"] = True
                        fields.append("bold")

                    if first_style.get("italic"):
                        text_style["italic"] = True
                        fields.append("italic")

                    if first_style.get("underline"):
                        text_style["underline"] = True
                        fields.append("underline")

                    font_size = first_style.get("font_size")
                    if font_size and font_size != 11:  # Only if not default
                        text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
                        fields.append("fontSize")

                    font_family = first_style.get("font_family")
                    if font_family and font_family != "Arial":  # Only if not default
                        text_style["weightedFontFamily"] = {"fontFamily": font_family}
                        fields.append("weightedFontFamily")

                    # Apply foreground color if it exists
                    fg_color = first_style.get("foreground_color")
                    if fg_color and fg_color.get("color", {}).get("rgbColor"):
                        text_style["foregroundColor"] = fg_color
                        fields.append("foregroundColor")

                    if text_style and fields:
                        requests.append(
                            {
                                "updateTextStyle": {
                                    "range": {
                                        "startIndex": current_index,
                                        "endIndex": end_index,
                                    },
                                    "textStyle": text_style,
                                    "fields": ",".join(fields),
                                }
                            }
                        )

                elif not text_was_replaced:
                    # Text unchanged - apply original detailed formatting
                    # This is safe because indices are still correct
                    element_index = current_index
                    for element in block["elements"]:
                        element_text = element["text"]
                        element_end = element_index + len(element_text)

                        style = element["style"]
                        text_style = {}
                        fields = []

                        if style.get("bold"):
                            text_style["bold"] = True
                            fields.append("bold")

                        if style.get("italic"):
                            text_style["italic"] = True
                            fields.append("italic")

                        if style.get("underline"):
                            text_style["underline"] = True
                            fields.append("underline")

                        if style.get("strikethrough"):
                            text_style["strikethrough"] = True
                            fields.append("strikethrough")

                        font_size = style.get("font_size")
                        if font_size:
                            text_style["fontSize"] = {
                                "magnitude": font_size,
                                "unit": "PT",
                            }
                            fields.append("fontSize")

                        font_family = style.get("font_family")
                        if font_family:
                            text_style["weightedFontFamily"] = {
                                "fontFamily": font_family
                            }
                            fields.append("weightedFontFamily")

                        fg_color = style.get("foreground_color")
                        if fg_color and fg_color.get("color", {}).get("rgbColor"):
                            text_style["foregroundColor"] = fg_color
                            fields.append("foregroundColor")

                        if text_style and fields:
                            requests.append(
                                {
                                    "updateTextStyle": {
                                        "range": {
                                            "startIndex": element_index,
                                            "endIndex": element_end,
                                        },
                                        "textStyle": text_style,
                                        "fields": ",".join(fields),
                                    }
                                }
                            )

                        element_index = element_end

                current_index = end_index

            elif block["type"] == "table":
                # Insert table (your existing code)
                requests.append(
                    {
                        "insertTable": {
                            "rows": block["rows"],
                            "columns": block["columns"],
                            "location": {"index": current_index},
                        }
                    }
                )
                current_index += 2  # Move past table

        # Execute all requests
        if requests:
            try:
                self.docs_service.documents().batchUpdate(
                    documentId=new_doc_id, body={"requests": requests}
                ).execute()
                print(f"✅ Applied {len(requests)} formatting operations")
            except Exception as e:
                print(f"⚠️ Error applying formatting: {e}")

    def list_my_docs(self, query: str = "") -> List[Dict]:
        """
        List Google Docs in user's Drive (for finding templates)

        Args:
            query: Optional search query

        Returns:
            List of documents with id, name, and url
        """
        try:
            # Search for Google Docs files
            search_query = "mimeType='application/vnd.google-apps.document'"
            if query:
                search_query += f" and name contains '{query}'"

            results = (
                self.drive_service.files()
                .list(
                    q=search_query,
                    pageSize=20,
                    fields="files(id, name, modifiedTime, webViewLink)",
                )
                .execute()
            )

            files = results.get("files", [])

            docs = []
            for file in files:
                docs.append(
                    {
                        "id": file["id"],
                        "name": file["name"],
                        "url": file["webViewLink"],
                        "modified": file["modifiedTime"],
                    }
                )

            return docs

        except HttpError as error:
            return []


# Example usage
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    # Test credentials
    test_creds = {
        "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    }

    extractor = DocumentFormatExtractor(test_creds)

    # Example: List user's documents
    print("📁 Your Google Docs:")
    docs = extractor.list_my_docs()
    for i, doc in enumerate(docs[:5], 1):
        print(f"{i}. {doc['name']} (ID: {doc['id']})")

    # Example: Extract format from a template
    # template_id = "YOUR_TEMPLATE_DOC_ID"
    # structure = extractor.extract_document_structure(template_id)
    # print("\n📋 Template Structure:")
    # print(f"Title: {structure['title']}")
    # print(f"Blocks: {len(structure['content_blocks'])}")

    # Example: Create from template
    # result = extractor.create_from_template(
    #     template_document_id="TEMPLATE_ID",
    #     new_title="Team Meeting - Jan 15, 2025",
    #     placeholder_values={
    #         "DATE": "January 15, 2025",
    #         "TIME": "2:00 PM",
    #         "VENUE": "Conference Room A"
    #     }
    # )
    # print(f"\n✅ Created: {result['url']}")
