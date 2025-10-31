"""
Mapping Agent API - Data Intelligence and Transformation Microservice
Handles file parsing, smart column mapping, data validation, and transformations
Completely independent of any destination (Sheets, Excel, Database, etc.)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import os
import uvicorn
import pandas as pd
import io
import json
from datetime import datetime
from dotenv import load_dotenv
from safexpressops_target_columns import SAFEXPRESSOPS_TARGET_COLUMNS


# Load environment variables from .env file
load_dotenv()

# Import the smart mapping engine
try:
    from smart_mapping_engine import SmartMappingEngine

    SMART_MAPPING_AVAILABLE = True
except ImportError:
    print(
        "⚠️ Warning: SmartMappingEngine not found. Smart mapping will use fallback logic."
    )
    SMART_MAPPING_AVAILABLE = False


# FastAPI app
app = FastAPI(title="Mapping Agent API", version="1.0.0")


# Pydantic Models
class ToolRequest(BaseModel):
    """Generic tool execution request"""

    tool: str
    inputs: Dict[str, Any]


class ToolResponse(BaseModel):
    """Generic tool execution response"""

    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# In-memory storage for mapping templates (use Redis/DB in production)
MAPPING_TEMPLATES = {}


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================


def parse_file(file_content: str, file_type: str = "csv") -> Dict[str, Any]:
    """
    Parse uploaded file content OR file path into structured data

    Args:
        file_content: File content as string/bytes OR file path
        file_type: Type of file (csv, xlsx, xls, excel, json)

    Returns:
        Dictionary with parsed data, columns, and metadata
    """
    try:
        # Check if file_content is actually a file path
        is_file_path = False
        if isinstance(file_content, str) and (
            file_content.startswith("/")
            or file_content.startswith("C:")
            or file_content.startswith("c:")
            or "\\" in file_content
        ):
            is_file_path = True
            print(f"📁 Detected file path: {file_content}")

        # Parse based on file type
        if file_type.lower() == "csv":
            if is_file_path:
                df = pd.read_csv(file_content)
            else:
                df = pd.read_csv(io.StringIO(file_content))

        elif file_type.lower() in ["xlsx", "xls", "excel"]:
            if is_file_path:
                df = pd.read_excel(file_content)  # ✅ Direct path reading
            else:
                df = pd.read_excel(
                    io.BytesIO(
                        file_content.encode()
                        if isinstance(file_content, str)
                        else file_content
                    )
                )

        elif file_type.lower() == "json":
            if is_file_path:
                df = pd.read_json(file_content)
            else:
                df = pd.read_json(io.StringIO(file_content))
        else:
            return {
                "success": False,
                "error": f"Unsupported file type: {file_type}. Supported: csv, xlsx, xls, excel, json",
            }

        # Clean the data
        df = df.dropna(how="all")  # Remove completely empty rows
        df.columns = df.columns.astype(str)  # Ensure column names are strings

        # Get metadata
        columns = df.columns.tolist()
        row_count = len(df)

        # Get sample data (first 5 rows)
        sample_df = df.head(5)

        # Infer data types for each column
        data_types = {}
        for col in columns:
            dtype = str(df[col].dtype)
            # Simplify dtype names
            if "int" in dtype:
                data_types[col] = "integer"
            elif "float" in dtype:
                data_types[col] = "float"
            elif "datetime" in dtype:
                data_types[col] = "datetime"
            elif "bool" in dtype:
                data_types[col] = "boolean"
            else:
                data_types[col] = "string"

        # Get sample values for each column
        sample_values = {}
        for col in columns:
            # Get first 3 non-null values
            non_null = df[col].dropna().head(3).tolist()
            sample_values[col] = [str(val) for val in non_null]

        return {
            "success": True,
            "columns": columns,
            "row_count": row_count,
            "column_count": len(columns),
            "data_types": data_types,
            "sample_values": sample_values,
            "sample_data": sample_df.to_dict("records"),
            "full_data": df.to_json(orient="records"),  # Full data as JSON string
            "metadata": {
                "parsed_at": datetime.now().isoformat(),
                "file_type": file_type,
                "has_header": True,
                "encoding": "utf-8",
            },
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to parse file: {str(e)}"}


def smart_column_mapping(
    source_columns: Any,  # Changed from List[str] to Any for flexibility
    target_columns: List[str] = None,  # ✅ CHANGED: Made optional with default None
    sample_data: Optional[List[Dict]] = None,
    source_data_types: Optional[Dict[str, str]] = None,
    sample_values: Optional[Dict[str, List[str]]] = None,
    skip_temporal: bool = True,
) -> Dict[str, Any]:
    """
    Intelligently map source columns to target columns using AI/heuristics

    Args:
        source_columns: List of source column names (or string representation)
        target_columns: List of target column names (optional, uses SAFEXPRESSOPS_TARGET_COLUMNS by default)
        sample_data: Optional sample data for better analysis
        source_data_types: Optional data types for source columns
        sample_values: Optional sample values for each source column

    Returns:
        Dictionary with mappings, confidence scores, and recommendations
    """
    try:
        print(f"\n🔍 Smart Column Mapping - Input Validation")
        print(f"   source_columns type: {type(source_columns).__name__}")

        if isinstance(source_columns, str):
            print(f"   ⚠️ source_columns is a string, parsing...")
            print(f"   String length: {len(source_columns)}")
            print(f"   First 100 chars: {source_columns[:100]}")

            import ast

            # Try multiple parsing strategies
            parsed = None

            # Strategy 1: JSON loads
            try:
                import json

                parsed = json.loads(source_columns)
                print(f"   ✅ Parsed with json.loads() - {len(parsed)} columns")
            except json.JSONDecodeError as e1:
                print(f"   ❌ json.loads() failed: {str(e1)}")

                # Strategy 2: Fix quotes and retry
                try:
                    fixed = source_columns.replace("'", '"')
                    parsed = json.loads(fixed)
                    print(f"   ✅ Parsed after fixing quotes - {len(parsed)} columns")
                except json.JSONDecodeError as e2:
                    print(f"   ❌ Quote fix failed: {str(e2)}")

                    # Strategy 3: ast.literal_eval
                    try:
                        parsed = ast.literal_eval(source_columns)
                        print(
                            f"   ✅ Parsed with ast.literal_eval() - {len(parsed)} columns"
                        )
                    except (ValueError, SyntaxError) as e3:
                        return {
                            "success": False,
                            "error": f"Could not parse source_columns: {str(e3)}",
                        }

            source_columns = parsed

        # ✅ Validate it's now a list
        if not isinstance(source_columns, list):
            return {
                "success": False,
                "error": f"source_columns must be a list, got {type(source_columns).__name__}. Value: {str(source_columns)[:200]}",
            }

        if len(source_columns) == 0:
            return {"success": False, "error": "source_columns is empty"}

        print(f"   ✅ Validated source_columns: {len(source_columns)} columns")
        print(f"   First 5 columns: {source_columns[:5]}")

        # ✅ NOW CONTINUE WITH YOUR EXISTING CODE BELOW
        # ✅ ADDED: Import operational columns
        from safexpressops_target_columns import (
            SAFEXPRESSOPS_OPERATIONAL_ONLY,
            TEMPORAL_COLUMNS,
        )

        # ✅ Use operational columns only if skip_temporal is True
        if target_columns is None:
            if skip_temporal:
                target_columns = SAFEXPRESSOPS_OPERATIONAL_ONLY
        # ✅ ADDED: Import operational columns
        from safexpressops_target_columns import (
            SAFEXPRESSOPS_OPERATIONAL_ONLY,
            TEMPORAL_COLUMNS,
        )

        # ✅ Use operational columns only if skip_temporal is True
        if target_columns is None and skip_temporal:
            target_columns = SAFEXPRESSOPS_OPERATIONAL_ONLY

        if SMART_MAPPING_AVAILABLE:
            # Use the smart mapping engine
            print("🧠 Using SmartMappingEngine for AI-powered mapping...")

            # Convert sample_data to DataFrame if provided
            sample_df = None
            if sample_data:
                try:
                    # ✅ Handle different sample_data formats
                    if isinstance(sample_data, str):
                        # If it's a JSON string, parse it
                        import json

                        sample_data = json.loads(sample_data)

                    if isinstance(sample_data, list):
                        # If it's a list of dicts (expected format)
                        sample_df = pd.DataFrame(sample_data)
                    elif isinstance(sample_data, dict):
                        # If it's a single dict, wrap it in a list
                        sample_df = pd.DataFrame([sample_data])
                    else:
                        print(
                            f"⚠️ Unexpected sample_data type: {type(sample_data)}, ignoring"
                        )
                        sample_df = None

                    if sample_df is not None and not sample_df.empty:
                        print(
                            f"   Sample data converted: {len(sample_df)} rows, {len(sample_df.columns)} columns"
                        )
                    else:
                        print(f"   No valid sample data provided")
                        sample_df = None

                except Exception as e:
                    print(
                        f"⚠️ Warning: Could not convert sample_data to DataFrame: {str(e)}"
                    )
                    print(f"   Continuing without sample data")
                    sample_df = None

            smart_engine = SmartMappingEngine()
            result = smart_engine.smart_map_columns(
                source_columns=source_columns,
                target_columns=target_columns,
                sample_data=sample_df,
            )

            # Convert smart engine result to our format
            mappings = {}
            confidence_scores = {}
            needs_review = []

            for source_col, mapping_info in result["mappings"].items():
                mappings[source_col] = mapping_info["target"]
                confidence_scores[source_col] = mapping_info["confidence_score"]

                if mapping_info["needs_review"]:
                    needs_review.append(
                        {
                            "source_column": source_col,
                            "suggested_target": mapping_info["target"],
                            "confidence": mapping_info["confidence_score"],
                            "reason": f"Low confidence ({mapping_info['confidence_level']})",
                        }
                    )

            return {
                "success": True,
                "mappings": mappings,
                "confidence_scores": confidence_scores,
                "needs_review": needs_review,
                "high_confidence_count": result["summary"]["high_confidence_mappings"],
                "accuracy_estimate": result["summary"]["accuracy_estimate"],
                "method": "smart_mapping_engine",
            }
        else:
            # Fallback: Simple string similarity matching
            print("📊 Using fallback string similarity matching...")
            from difflib import SequenceMatcher

            mappings = {}
            confidence_scores = {}
            needs_review = []

            for source_col in source_columns:
                best_match = None
                best_score = 0.0

                for target_col in target_columns:
                    # Calculate similarity score
                    score = SequenceMatcher(
                        None, source_col.lower(), target_col.lower()
                    ).ratio()

                    if score > best_score:
                        best_score = score
                        best_match = target_col

                mappings[source_col] = best_match if best_score > 0.3 else None
                confidence_scores[source_col] = best_score

                # Flag for review if confidence is low
                if best_score < 0.7:
                    needs_review.append(
                        {
                            "source_column": source_col,
                            "suggested_target": best_match,
                            "confidence": best_score,
                            "reason": "Low string similarity",
                        }
                    )

            high_confidence = sum(
                1 for score in confidence_scores.values() if score >= 0.7
            )

            return {
                "success": True,
                "mappings": mappings,
                "confidence_scores": confidence_scores,
                "needs_review": needs_review,
                "high_confidence_count": high_confidence,
                "accuracy_estimate": (
                    sum(confidence_scores.values()) / len(confidence_scores)
                    if confidence_scores
                    else 0
                ),
                "method": "string_similarity_fallback",
            }
    except Exception as e:
        print(f"❌ Smart mapping error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": f"Mapping failed: {str(e)}"}


def validate_mapping(
    mappings: Dict[str, str],
    source_columns: List[str],
    target_columns: List[str],
    sample_data: Optional[List[Dict]] = None,
    require_all_targets: bool = False,
) -> Dict[str, Any]:
    """
    Validate that mapping configuration is correct and complete

    Args:
        mappings: Dictionary of source -> target column mappings
        source_columns: List of all source columns
        target_columns: List of all target columns
        sample_data: Optional sample data for validation
        require_all_targets: If True, ensure all target columns are mapped

    Returns:
        Validation result with errors and warnings
    """
    try:
        errors = []
        warnings = []

        # Check for unmapped source columns
        unmapped_sources = [col for col in source_columns if col not in mappings]
        if unmapped_sources:
            warnings.append(
                {
                    "type": "unmapped_source_columns",
                    "message": f"{len(unmapped_sources)} source columns not mapped",
                    "columns": unmapped_sources,
                }
            )

        # Check for invalid target columns
        invalid_targets = []
        for source, target in mappings.items():
            if target and target not in target_columns:
                invalid_targets.append({"source": source, "invalid_target": target})

        if invalid_targets:
            errors.append(
                {
                    "type": "invalid_target_columns",
                    "message": "Some mappings point to non-existent target columns",
                    "mappings": invalid_targets,
                }
            )

        # Check for duplicate mappings (multiple sources -> same target)
        target_usage = {}
        for source, target in mappings.items():
            if target:
                if target not in target_usage:
                    target_usage[target] = []
                target_usage[target].append(source)

        duplicate_targets = {
            target: sources
            for target, sources in target_usage.items()
            if len(sources) > 1
        }
        if duplicate_targets:
            warnings.append(
                {
                    "type": "duplicate_target_mappings",
                    "message": "Multiple source columns mapped to same target",
                    "duplicates": duplicate_targets,
                }
            )

        # Check if all required targets are mapped
        if require_all_targets:
            mapped_targets = set(mappings.values())
            unmapped_targets = [
                col for col in target_columns if col not in mapped_targets
            ]
            if unmapped_targets:
                warnings.append(
                    {
                        "type": "unmapped_target_columns",
                        "message": f"{len(unmapped_targets)} target columns not filled",
                        "columns": unmapped_targets,
                    }
                )

        # Data type compatibility check (if sample data provided)
        type_warnings = []
        if sample_data:
            df = pd.DataFrame(sample_data)
            for source, target in mappings.items():
                if target and source in df.columns:
                    # Check if column has numeric data
                    try:
                        pd.to_numeric(df[source])
                        # Could add more sophisticated type checking here
                    except:
                        pass

        is_valid = len(errors) == 0

        return {
            "success": True,
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "total_mappings": len(mappings),
                "valid_mappings": len([m for m in mappings.values() if m]),
                "error_count": len(errors),
                "warning_count": len(warnings),
            },
        }

    except Exception as e:
        return {"success": False, "error": f"Validation failed: {str(e)}"}


def extract_date_from_data(
    data: str,
    date_column_hints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Extract date from parsed data"""
    try:
        print(f"\n📅 Extracting date from data...")
        df = pd.read_json(data)

        if date_column_hints is None:
            date_column_hints = ["Date", "date", "DATE", "Day", "day"]

        date_col_name = None
        for hint in date_column_hints:
            if hint in df.columns:
                date_col_name = hint
                break

        if not date_col_name:
            date_col_name = df.columns[0]

        first_date_value = df[date_col_name].iloc[0]

        date_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d-%b-%y",
            "%d-%b-%Y",
            "%m/%d/%Y",
            "%d/%m/%Y",
        ]

        parsed_date = None
        if isinstance(first_date_value, (pd.Timestamp, datetime)):
            parsed_date = first_date_value
        else:
            date_str = str(first_date_value).strip()
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    break
                except:
                    continue
            if not parsed_date:
                try:
                    parsed_date = pd.to_datetime(date_str)
                except:
                    pass

        if not parsed_date:
            return {
                "success": False,
                "error": f"Could not parse date: {first_date_value}",
            }

        if isinstance(parsed_date, pd.Timestamp):
            parsed_date = parsed_date.to_pydatetime()

        print(f"   ✅ Parsed date: {parsed_date.strftime('%Y-%m-%d')}")

        return {
            "success": True,
            "date": parsed_date.strftime("%Y-%m-%d"),
            "date_object": parsed_date.isoformat(),
            "source_column": date_col_name,
            "formatted_display": parsed_date.strftime("%d-%b-%Y"),
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to extract date: {str(e)}"}


def transform_data(
    source_data: str,  # JSON string from parse_file
    mappings: Any,  # Changed from Dict to Any for flexibility
    target_columns: Optional[List[str]] = None,
    fill_missing: bool = True,
) -> Dict[str, Any]:
    """
    Apply mappings and transform source data to target structure

    Args:
        source_data: JSON string of source data (from parse_file)
        mappings: Dictionary of source -> target column mappings (or string representation)
        target_columns: Optional list of target columns (for ordering)
        fill_missing: If True, fill unmapped target columns with empty values

    Returns:
        Transformed data ready for upload to destination
    """
    try:
        # ✅ DEFENSIVE TYPE CHECK - Handle string representation of dict
        if isinstance(mappings, str):
            print(f"⚠️ Warning: mappings received as string, converting to dict")
            print(f"   Original value: {mappings[:200]}...")  # Show first 200 chars
            import ast

            try:
                mappings = ast.literal_eval(mappings)
                print(f"   Converted successfully")
            except (ValueError, SyntaxError) as e:
                # If literal_eval fails, try JSON
                import json

                try:
                    mappings = json.loads(mappings)
                    print(f"   Converted via JSON successfully")
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": f"Could not parse mappings: {str(e)}",
                    }

        # Validate it's now a dict
        if not isinstance(mappings, dict):
            return {
                "success": False,
                "error": f"mappings must be a dict, got {type(mappings).__name__}. Value: {mappings}",
            }

        print(f"\n🔄 Transform Data")
        print(f"   Mappings ({len(mappings)}): {mappings}")

        # Parse source data
        source_df = pd.read_json(source_data)

        print(f"   Source data shape: {source_df.shape}")
        print(f"   Source columns: {list(source_df.columns)}")

        # Create new dataframe with target structure
        transformed_rows = []

        for _, source_row in source_df.iterrows():
            target_row = {}

            # Apply mappings
            for source_col, target_col in mappings.items():
                if target_col and source_col in source_row:
                    value = source_row[source_col]
                    # Convert to string and handle NaN/None
                    if pd.notna(value):
                        target_row[target_col] = str(value).strip()
                    else:
                        target_row[target_col] = ""

            # Fill missing target columns if requested
            if fill_missing and target_columns:
                for col in target_columns:
                    if col not in target_row:
                        target_row[col] = ""

            transformed_rows.append(target_row)

        # Convert to DataFrame for easier manipulation
        transformed_df = pd.DataFrame(transformed_rows)

        # Reorder columns if target_columns specified
        if target_columns:
            # Only include columns that exist in transformed_df
            available_cols = [
                col for col in target_columns if col in transformed_df.columns
            ]
            transformed_df = transformed_df[available_cols]

        print(f"   Transformed shape: {transformed_df.shape}")
        print(f"   Transformed columns: {list(transformed_df.columns)}")

        # Get statistics
        mapped_columns = [col for col in mappings.values() if col]
        unmapped_source = [col for col in source_df.columns if col not in mappings]

        return {
            "success": True,
            "transformed_data": transformed_df.to_json(orient="records"),  # JSON string
            "row_count": len(transformed_df),
            "column_count": len(transformed_df.columns),
            "columns": transformed_df.columns.tolist(),
            "statistics": {
                "source_columns": len(source_df.columns),
                "target_columns": len(transformed_df.columns),
                "mapped_columns": len(mapped_columns),
                "unmapped_source_columns": len(unmapped_source),
                "rows_processed": len(transformed_df),
            },
            "unmapped_source_columns": unmapped_source,
        }

    except Exception as e:
        print(f"❌ Transformation error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": f"Transformation failed: {str(e)}"}


def save_mapping_template(
    template_name: str,
    mappings: Dict[str, str],
    target_columns: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Save mapping configuration as a reusable template

    Args:
        template_name: Unique name for the template
        mappings: Column mappings to save
        target_columns: Optional target column list
        metadata: Optional metadata (description, tags, etc.)

    Returns:
        Success status and template ID
    """
    try:
        template_id = f"template_{template_name.lower().replace(' ', '_')}"

        template = {
            "id": template_id,
            "name": template_name,
            "mappings": mappings,
            "target_columns": target_columns or [],
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        # Store in memory (use Redis/DB in production)
        MAPPING_TEMPLATES[template_id] = template

        return {
            "success": True,
            "template_id": template_id,
            "template_name": template_name,
            "message": f"Template '{template_name}' saved successfully",
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to save template: {str(e)}"}


def load_mapping_template(template_name: str) -> Dict[str, Any]:
    """
    Load a saved mapping template

    Args:
        template_name: Name or ID of the template to load

    Returns:
        Template configuration with mappings
    """
    try:
        # Try as ID first
        template_id = f"template_{template_name.lower().replace(' ', '_')}"

        if template_id in MAPPING_TEMPLATES:
            template = MAPPING_TEMPLATES[template_id]
        else:
            # Try finding by name
            found = None
            for temp_id, temp in MAPPING_TEMPLATES.items():
                if temp["name"].lower() == template_name.lower():
                    found = temp
                    break

            if not found:
                return {
                    "success": False,
                    "error": f"Template '{template_name}' not found",
                }

            template = found

        return {
            "success": True,
            "template_id": template["id"],
            "template_name": template["name"],
            "mappings": template["mappings"],
            "target_columns": template.get("target_columns", []),
            "metadata": template.get("metadata", {}),
            "created_at": template.get("created_at"),
            "updated_at": template.get("updated_at"),
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to load template: {str(e)}"}


def list_mapping_templates() -> Dict[str, Any]:
    """
    List all saved mapping templates

    Returns:
        List of available templates with metadata
    """
    try:
        templates = []
        for template_id, template in MAPPING_TEMPLATES.items():
            templates.append(
                {
                    "id": template["id"],
                    "name": template["name"],
                    "mapping_count": len(template.get("mappings", {})),
                    "created_at": template.get("created_at"),
                    "metadata": template.get("metadata", {}),
                }
            )

        return {"success": True, "templates": templates, "count": len(templates)}

    except Exception as e:
        return {"success": False, "error": f"Failed to list templates: {str(e)}"}


def extract_dates_from_all_rows(
    data: str, date_column_name: str = "Date"
) -> Dict[str, Any]:
    """
    Extract dates from ALL rows for date-based row matching

    Args:
        data: JSON string of full data
        date_column_name: Name of the date column

    Returns:
        List of {row_index, date, data} for each row
    """
    try:
        print(f"\n📅 Extracting dates from all rows...")
        df = pd.read_json(data)

        if date_column_name not in df.columns:
            return {
                "success": False,
                "error": f"Date column '{date_column_name}' not found. Available: {list(df.columns)}",
            }

        # Extract dates for all rows
        rows_with_dates = []
        date_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d-%b-%y",
            "%d-%b-%Y",
            "%m/%d/%Y",
            "%d/%m/%Y",
        ]

        for idx, row in df.iterrows():
            date_value = row[date_column_name]

            # Parse date
            parsed_date = None
            if isinstance(date_value, (pd.Timestamp, datetime)):
                parsed_date = date_value
            else:
                date_str = str(date_value).strip()
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
                if not parsed_date:
                    try:
                        parsed_date = pd.to_datetime(date_str)
                    except:
                        pass

            if parsed_date:
                if isinstance(parsed_date, pd.Timestamp):
                    parsed_date = parsed_date.to_pydatetime()

                rows_with_dates.append(
                    {
                        "row_index": int(idx),
                        "date": parsed_date.strftime("%Y-%m-%d"),
                        "date_formatted": parsed_date.strftime(
                            "%d-%b-%y"
                        ),  # Matches your sheet format
                        "row_data": row.to_dict(),
                    }
                )

        print(f"   ✅ Extracted {len(rows_with_dates)} dates")
        if rows_with_dates:
            print(
                f"   Date range: {rows_with_dates[0]['date']} to {rows_with_dates[-1]['date']}"
            )

        return {
            "success": True,
            "rows_with_dates": rows_with_dates,
            "total_rows": len(rows_with_dates),
            "date_column": date_column_name,
        }

    except Exception as e:
        print(f"❌ Error extracting dates: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": f"Failed to extract dates: {str(e)}"}


# ============================================================
# TOOL REGISTRY
# ============================================================

TOOL_REGISTRY = {
    "parse_file": {
        "func": parse_file,
        "description": "Parse CSV/Excel/JSON files into structured data",
    },
    "extract_dates_from_all_rows": {  # ✅ NEW
        "func": extract_dates_from_all_rows,
        "description": "Extract dates from all rows for date-based matching",
    },
    "smart_column_mapping": {
        "func": smart_column_mapping,
        "description": "Intelligently map source to target columns with AI",
    },
    "validate_mapping": {
        "func": validate_mapping,
        "description": "Validate mapping configuration for errors",
    },
    "transform_data": {
        "func": transform_data,
        "description": "Apply mappings and transform data structure",
    },
    "save_mapping_template": {
        "func": save_mapping_template,
        "description": "Save mapping configuration as reusable template",
    },
    "load_mapping_template": {
        "func": load_mapping_template,
        "description": "Load saved mapping template",
    },
    "list_mapping_templates": {
        "func": list_mapping_templates,
        "description": "List all saved mapping templates",
    },
    "extract_date_from_data": {
        "func": extract_date_from_data,
        "description": "Extract date from parsed data for data identification",
    },
}


# ============================================================
# API ENDPOINTS
# ============================================================


@app.post("/execute_task", response_model=ToolResponse)
async def execute_tool(request: ToolRequest):
    """
    Execute a mapping tool

    Request body:
        - tool: Name of the tool to execute
        - inputs: Dictionary of tool inputs

    Returns:
        ToolResponse with success status and result/error
    """
    try:
        print(f"\n🗺️ Mapping Agent - Tool: {request.tool}")
        print(f"   Inputs: {list(request.inputs.keys())}")

        # Get tool from registry
        tool_info = TOOL_REGISTRY.get(request.tool)
        if not tool_info:
            available_tools = list(TOOL_REGISTRY.keys())
            return ToolResponse(
                success=False,
                error=f"Unknown tool: {request.tool}. Available: {available_tools}",
            )

        # Execute tool
        result = tool_info["func"](**request.inputs)

        print(
            f"   {'✅' if result.get('success') else '❌'} Result: {result.get('success', False)}"
        )

        return ToolResponse(
            success=result.get("success", False),
            result=result if result.get("success") else None,
            error=result.get("error") if not result.get("success") else None,
        )

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return ToolResponse(
            success=False,
            error=f"Tool execution failed: {str(e)}",
        )


@app.get("/tools")
async def list_tools():
    """List all available tools"""
    return {
        "tools": [
            {"name": name, "description": info["description"]}
            for name, info in TOOL_REGISTRY.items()
        ],
        "count": len(TOOL_REGISTRY),
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "mapping-agent",
        "version": "1.0.0",
        "smart_mapping_available": SMART_MAPPING_AVAILABLE,
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Mapping Agent API",
        "version": "1.0.0",
        "description": "Data intelligence and transformation microservice",
        "features": [
            "File parsing (CSV, Excel, JSON)",
            "AI-powered column mapping",
            "Data validation",
            "Data transformation",
            "Template management",
        ],
        "endpoints": {
            "execute": "/execute (POST) - Execute a mapping tool",
            "tools": "/tools (GET) - List available tools",
            "health": "/health (GET) - Health check",
            "docs": "/docs (GET) - Swagger documentation",
        },
    }


# Run the server
if __name__ == "__main__":
    port = int(os.getenv("MAPPING_AGENT_PORT", "8004"))
    print(f"🚀 Starting Mapping Agent on port {port}")
    print(f"📚 API Documentation: http://localhost:{port}/docs")
    print(f"🔧 Available tools: {list(TOOL_REGISTRY.keys())}")
    print(
        f"🧠 Smart Mapping: {'Enabled' if SMART_MAPPING_AVAILABLE else 'Fallback mode'}"
    )
    uvicorn.run(app, host="0.0.0.0", port=port)
