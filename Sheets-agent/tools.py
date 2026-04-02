"""
safexpressops_sheets_agent.py - Google Sheets agent with smart mapping
Integrates with your existing LangGraph multi-agent system
"""

import json
import pandas as pd
import io
from typing import Dict, List, Any
from langchain_core.messages import AIMessage
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from smart_mapping_engine import SmartMappingEngine

# SafExpressOps target columns (from your DATA ENTRY sheet)
SAFEXPRESSOPS_COLUMNS = [
    "Wee",
    "Week",
    "Date",
    "Day",
    "Total Manhours",
    "Safe man-hours",
    "No Lost Time Incident Rate",
    "Cummulative Safe manhours",
    "Losttime Incident",
    "Days Without Lost Time Incident",
    "Cummulative Days Without Lost Time Incident",
    "Cycle Count Accuracy",
    "Warehouse Damage Incident",
    "FEFO Incident",
    "Expired Product Incident",
    "Damaged from CV",
    "No. of CV Received",
    "INBOUND OTIF",
    "Ave Picked Qty Per Hr",
    "CTS %",
    "Present",
    # Add more as needed from your 114 columns
]


def create_sheets_tools(credentials: Dict[str, str]):
    """Create Google Sheets tools with injected credentials"""

    # Initialize the smart mapping engine once
    smart_engine = SmartMappingEngine()

    def _get_sheets_service():
        """Helper to create authenticated Sheets service"""
        from google.auth.transport.requests import Request as AuthRequest
        creds = Credentials(
            token=credentials.get("access_token"),
            refresh_token=credentials.get("refresh_token"),
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
            token_uri="https://oauth2.googleapis.com/token",
        )
        if creds.refresh_token:
            try:
                creds.refresh(AuthRequest())
            except Exception:
                pass
        return build("sheets", "v4", credentials=creds)

    def _parse_uploaded_file_impl(
        file_content: str, file_type: str = "csv"
    ) -> Dict[str, Any]:
        """Parse uploaded file content into structured data"""
        try:
            if file_type.lower() == "csv":
                df = pd.read_csv(io.StringIO(file_content))
            elif file_type.lower() in ["xlsx", "xls", "excel"]:
                df = pd.read_excel(
                    io.BytesIO(
                        file_content.encode()
                        if isinstance(file_content, str)
                        else file_content
                    )
                )
            else:
                return {
                    "success": False,
                    "error": f"Unsupported file type: {file_type}",
                }

            # Clean the data
            df = df.dropna(how="all")
            df.columns = df.columns.astype(str)

            # Get sample data for smart analysis
            sample_data = df.head(5)

            return {
                "success": True,
                "columns": df.columns.tolist(),
                "row_count": len(df),
                "sample_data": sample_data.to_dict("records"),
                "dataframe": df.to_json(),
                "sample_dataframe": sample_data.to_json(),
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to parse file: {str(e)}"}

    def _smart_column_mapping_impl(
        source_columns: List[str],
        sample_data_json: str = None,
        target_columns: List[str] = None,
    ) -> Dict[str, Any]:
        """Use SmartMappingEngine for intelligent column mapping"""

        print("🧠 Using Smart Mapping Engine...")

        if target_columns is None:
            target_columns = SAFEXPRESSOPS_COLUMNS

        # Parse sample data if provided
        sample_data = None
        if sample_data_json:
            try:
                sample_data = pd.read_json(sample_data_json)
                print(f"📊 Analyzing {len(sample_data)} sample rows")
            except Exception as e:
                print(f"⚠️ Could not parse sample data: {e}")

        # Use the smart mapping engine
        smart_result = smart_engine.smart_map_columns(
            source_columns=source_columns,
            target_columns=target_columns,
            sample_data=sample_data,
        )

        # Convert smart engine result to expected format
        mappings = {}
        confidence_scores = {}
        needs_review = {}

        for source_col, mapping_info in smart_result["mappings"].items():
            mappings[source_col] = mapping_info["target"]
            confidence_scores[source_col] = mapping_info["confidence_score"]

            if mapping_info["needs_review"]:
                needs_review[source_col] = {
                    "suggested": mapping_info["target"],
                    "confidence": mapping_info["confidence_score"],
                    "reason": f"Confidence level: {mapping_info['confidence_level']}",
                }

        return {
            "success": True,
            "mappings": mappings,
            "confidence_scores": confidence_scores,
            "needs_user_review": needs_review,
            "high_confidence_count": smart_result["summary"][
                "high_confidence_mappings"
            ],
            "accuracy_estimate": smart_result["summary"]["accuracy_estimate"],
            "smart_analysis": True,
        }

    def _upload_to_sheets_impl(
        file_data: str,
        sheet_id: str,
        mappings: Dict[str, str],
        sheet_name: str = "DATA ENTRY",
    ) -> Dict[str, Any]:
        """Upload mapped data to Google Sheets"""
        try:
            # Parse the file data
            df = pd.read_json(file_data)

            # Get Sheets service
            service = _get_sheets_service()

            # Get existing sheet headers
            headers_range = f"{sheet_name}!1:1"
            headers_result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=sheet_id, range=headers_range)
                .execute()
            )

            existing_headers = headers_result.get("values", [[]])[0]

            # Prepare mapped data
            mapped_rows = []
            for _, row in df.iterrows():
                new_row = [""] * len(existing_headers)

                for source_col, target_col in mappings.items():
                    if target_col and target_col in existing_headers:
                        target_index = existing_headers.index(target_col)
                        value = row.get(source_col, "")

                        if pd.notna(value):
                            new_row[target_index] = str(value).strip()
                        else:
                            new_row[target_index] = ""

                mapped_rows.append(new_row)

            # Find next empty row and insert data
            all_data = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=sheet_id, range=f"{sheet_name}!A:A")
                .execute()
            )

            next_row = len(all_data.get("values", [])) + 1
            range_name = f"{sheet_name}!A{next_row}"

            result = (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": mapped_rows},
                )
                .execute()
            )

            return {
                "success": True,
                "rows_added": len(mapped_rows),
                "start_row": next_row,
                "range_updated": result.get("updates", {}).get("updatedRange"),
                "message": f"Successfully uploaded {len(mapped_rows)} rows to {sheet_name}",
            }

        except Exception as e:
            return {"success": False, "error": f"Upload failed: {str(e)}"}

    return [
        {
            "name": "parse_uploaded_file",
            "func": _parse_uploaded_file_impl,
            "description": "Parse uploaded file and extract sample data for smart analysis",
        },
        {
            "name": "smart_column_mapping",
            "func": _smart_column_mapping_impl,
            "description": "Intelligently map columns using AI analysis of names and data patterns",
        },
        {
            "name": "upload_to_sheets",
            "func": _upload_to_sheets_impl,
            "description": "Upload mapped data to Google Sheets",
        },
    ]


def sheets_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Google Sheets agent node for SafExpressOps multi-agent system"""

    print("\n📊 SafExpressOps Sheets Agent Node")

    plan_steps = state["plan"].get("plan", [])
    current_step = state["current_step"]

    if current_step >= len(plan_steps):
        return state

    step = plan_steps[current_step]

    if step["agent"] != "sheets_agent":
        return state

    tool_name = step["tool"]
    inputs = step["inputs"]

    # Variable substitution (following your existing Jinja2 pattern)
    from jinja2 import Template

    substituted_inputs = {}
    for key, value in inputs.items():
        if isinstance(value, str):
            template = Template(value)
            substituted_inputs[key] = template.render(**state["context"])
        else:
            substituted_inputs[key] = value

    print(f"🔧 Executing: {tool_name}")
    print(f"   Inputs: {substituted_inputs}")

    # Get credentials from state
    credentials = state.get("credentials", {})

    if not credentials.get("access_token"):
        return {
            **state,
            "agent_results": state["agent_results"]
            + [
                {
                    "success": False,
                    "error": "No Google credentials available",
                    "action_required": "oauth_connect",
                }
            ],
            "messages": state["messages"]
            + [AIMessage(content="❌ Sheets Agent: Authentication required")],
        }

    # Create tools with credentials
    tools = create_sheets_tools(credentials)
    tool_map = {tool["name"]: tool["func"] for tool in tools}

    # Execute the requested tool
    if tool_name in tool_map:
        result = tool_map[tool_name](**substituted_inputs)
    else:
        result = {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(tool_map.keys()),
        }

    # Extract output variables
    output_vars = step.get("output_variables", {})
    new_context = {**state["context"]}

    for new_var, source_field in output_vars.items():
        if source_field in result:
            new_context[new_var] = result[source_field]
            print(f"   ✓ {new_var} = {result[source_field]}")

    # Prepare response message
    if result.get("success"):
        message = f"✅ Sheets: {tool_name} completed - {result.get('message', 'Done')}"
    else:
        message = (
            f"❌ Sheets: {tool_name} failed - {result.get('error', 'Unknown error')}"
        )

    return {
        **state,
        "context": new_context,
        "current_step": current_step + 1,
        "agent_results": state["agent_results"] + [result],
        "messages": state["messages"] + [AIMessage(content=message)],
    }
