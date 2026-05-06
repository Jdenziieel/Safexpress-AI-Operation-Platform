import json
import boto3
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher

logger = logging.getLogger()
logger.setLevel(logging.INFO)

lambda_client = boto3.client('lambda', region_name='ap-southeast-1')


def lambda_handler(event, context):
    try:
        logger.info(f"📨 OPR Agent received event keys: {list(event.keys())}")

        # Handle both API Gateway proxy and direct Lambda invocation
        if 'body' in event and 'workflow_type' not in event:
            body = event['body']
            if isinstance(body, str):
                body = json.loads(body)
        else:
            body = event  # Direct invocation from wrapper

        workflow_type = body.get('workflow_type', 'process')

        if workflow_type == 'preview':
            return handle_preview_workflow(body)
        else:
            return handle_process_workflow(body)

    except Exception as e:
        logger.error(f"❌ Lambda handler error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'statusCode': 500,
            'body': json.dumps({'success': False, 'error': str(e)})
        }

def invoke_mapping_agent(tool_name, inputs):
    try:
        response = lambda_client.invoke(
            FunctionName='safexpressops-mapping-agent',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                'tool': tool_name,
                'inputs': inputs
            })
        )
        
        result = json.loads(response['Payload'].read())
        
        # Handle nested body if present
        if 'body' in result:
            body = json.loads(result['body']) if isinstance(result['body'], str) else result['body']
        else:
            body = result

        if not body.get('success'):
            raise Exception(f"{tool_name} failed: {body.get('error')}")

        return body.get('result', body)

    except Exception as e:
        logger.error(f"❌ Error calling mapping agent ({tool_name}): {str(e)}")
        raise

def invoke_sheets_agent(tool_name, inputs, credentials_dict):
    """Helper to call sheets agent"""
    try:
        payload = {
            'tool': tool_name,
            'inputs': inputs,
            'credentials_dict': credentials_dict
        }
        
        logger.info(f"📡 Calling sheets agent: {tool_name}")
        
        response = lambda_client.invoke(
            FunctionName='safexpressops-sheets-agent',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        result = json.loads(response['Payload'].read())
        
        # Check if there's a nested body
        if 'body' in result:
            body = json.loads(result['body']) if isinstance(result['body'], str) else result['body']
        else:
            body = result
        
        if not body.get('success'):
            error_msg = body.get('error', 'Unknown sheets agent error')
            logger.error(f"❌ Sheets agent error: {error_msg}")
            raise Exception(error_msg)
        
        return body.get('result', body)
        
    except Exception as e:
        logger.error(f"❌ Error calling sheets agent ({tool_name}): {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def calculate_confidence(source_col: str, target_col: str) -> float:
    """
    Calculate confidence score based on string similarity
    
    Args:
        source_col: Source column name from Excel
        target_col: Target column name from Google Sheets (can be None)
    
    Returns:
        Confidence score between 0.0 and 1.0
    """
    # Handle None/empty target columns
    if not target_col or not source_col:
        return 0.0
    
    # Normalize strings
    s1 = source_col.lower().strip()
    s2 = target_col.lower().strip()
    
    # Exact match
    if s1 == s2:
        return 1.0
    
    # Remove common variations
    s1_clean = s1.replace('_', ' ').replace('-', ' ')
    s2_clean = s2.replace('_', ' ').replace('-', ' ')
    
    if s1_clean == s2_clean:
        return 0.98
    
    # Substring match
    if s1 in s2 or s2 in s1:
        return 0.92
    
    # Calculate similarity
    similarity = SequenceMatcher(None, s1, s2).ratio()
    
    # Boost for word matches
    s1_words = set(s1.split())
    s2_words = set(s2.split())
    common_words = s1_words & s2_words
    
    if common_words:
        word_overlap = len(common_words) / max(len(s1_words), len(s2_words))
        similarity = max(similarity, word_overlap * 0.85)
    
    return similarity


def detect_and_validate_file_type(file_data):
    """
    Detect and validate file type from base64 content
    Returns: ('csv' | 'xlsx', None) or (None, error_message)
    """
    try:
        import base64
        import zipfile
        import io
        
        # Decode first 200 bytes to check signature
        decoded_sample = base64.b64decode(file_data[:200])
        
        # Excel files start with PK (ZIP signature)
        if decoded_sample.startswith(b'PK\x03\x04'):
            try:
                full_decoded = base64.b64decode(file_data)
                
                with zipfile.ZipFile(io.BytesIO(full_decoded), 'r') as zip_ref:
                    bad_file = zip_ref.testzip()
                    if bad_file:
                        logger.error(f"   ❌ Corrupted file detected: {bad_file}")
                        return (None, "Excel file is corrupted. Please try re-saving or re-exporting the file.")
                    
                    file_list = zip_ref.namelist()
                    excel_markers = [
                        '[Content_Types].xml',
                        'xl/workbook.xml',
                        'xl/worksheets/',
                        '_rels/.rels',
                    ]
                    
                    if any(any(marker in f for f in file_list) for marker in excel_markers):
                        logger.info("   ✅ Validated: Excel file (integrity checked)")
                        return ('xlsx', None)
                    else:
                        logger.warning("   ⚠️ Valid ZIP but not Excel format")
                        return (None, "File is a ZIP archive but not Excel format. Please upload .xlsx or .csv files.")
                        
            except zipfile.BadZipFile:
                logger.error("   ❌ Corrupted ZIP/Excel file")
                return (None, "Excel file is corrupted or incomplete. Please try uploading again.")
            except Exception as e:
                logger.error(f"   ❌ Excel validation error: {str(e)}")
                return (None, f"Could not validate Excel file: {str(e)}")
        
        # Try to decode as CSV
        try:
            full_decoded = base64.b64decode(file_data).decode('utf-8')
            first_lines = full_decoded.split('\n')[:5]
            
            if any(',' in line for line in first_lines):
                import csv
                try:
                    csv_reader = csv.reader(io.StringIO('\n'.join(first_lines)))
                    rows = list(csv_reader)
                    if len(rows) > 0 and len(rows[0]) > 0:
                        logger.info(f"   ✅ Validated: CSV file ({len(rows[0])} columns detected)")
                        return ('csv', None)
                    else:
                        logger.warning("   ⚠️ CSV appears empty")
                        return (None, "CSV file appears to be empty or corrupted.")
                except csv.Error as e:
                    logger.error(f"   ❌ CSV parsing error: {str(e)}")
                    return (None, f"CSV file is malformed: {str(e)}")
        except UnicodeDecodeError:
            pass
        
        # Check for old Excel format
        if decoded_sample.startswith(b'\xd0\xcf\x11\xe0'):
            logger.info("   ✅ Validated: XLS file (old Excel format)")
            return ('xlsx', None)
        
        # Check for rejected file types
        if decoded_sample.startswith(b'%PDF'):
            logger.warning("   ❌ Rejected: PDF file")
            return (None, "PDF files are not supported. Please upload Excel (.xlsx) or CSV (.csv) files.")
        
        if decoded_sample.startswith(b'\xff\xd8\xff'):
            logger.warning("   ❌ Rejected: Image file (JPEG)")
            return (None, "Image files are not supported. Please upload Excel (.xlsx) or CSV (.csv) files.")
        
        if decoded_sample.startswith(b'\x89PNG'):
            logger.warning("   ❌ Rejected: Image file (PNG)")
            return (None, "Image files are not supported. Please upload Excel (.xlsx) or CSV (.csv) files.")
        
        logger.warning(f"   ❌ Unknown file type. First bytes: {decoded_sample[:20]}")
        return (None, "Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV (.csv) files only.")
        
    except Exception as e:
        logger.error(f"   ❌ File validation error: {str(e)}")
        return (None, f"File validation failed: {str(e)}")


def handle_preview_workflow(body):
    """Preview workflow - shows what will change"""
    try:
        logger.info("🔍 Starting PREVIEW workflow...")
        
        file_data = body.get('file_data')
        target_sheet_url = body.get('target_sheet_url')
        google_credentials = body.get('google_credentials')
        
        if not all([file_data, target_sheet_url, google_credentials]):
            raise ValueError("Missing required fields")
        
        # Extract sheet ID
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', target_sheet_url)
        if not match:
            raise ValueError("Invalid Google Sheets URL")
        
        sheet_id = match.group(1)
        logger.info(f"📄 Sheet ID: {sheet_id}")
        
        # Step 0: Validate file type
        logger.info("📝 Step 0: Validating file type...")
        file_type, validation_error = detect_and_validate_file_type(file_data)
        
        if validation_error:
            logger.error(f"❌ File validation failed: {validation_error}")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': validation_error
                })
            }
        
        logger.info(f"✅ File type validated: {file_type.upper()}")
        
        # Step 1: Parse file
        logger.info(f"📝 Step 1: Parsing {file_type.upper()} file...")
        sheet_name = None if file_type == 'csv' else 0
        
        parsed_data = invoke_mapping_agent('parse_file', {
            'file_content': file_data,
            'file_type': file_type,
            'sheet_name': sheet_name
        })
        logger.info(f"✅ Parsed: {parsed_data.get('row_count', 0)} rows, {len(parsed_data.get('columns', []))} columns")
        
        # Step 2: Extract dates
        logger.info("📝 Step 2: Extracting dates...")
        dates_data = invoke_mapping_agent('extract_dates_from_all_rows', {
            'data': parsed_data['full_data'],
            'date_column_name': 'Date'
        })
        rows_with_dates = dates_data.get('rows_with_dates', [])
        logger.info(f"✅ Extracted {len(rows_with_dates)} dates")
        
        # Step 3: Smart mapping
        logger.info("📝 Step 3: Smart column mapping...")
        mapping_data = invoke_mapping_agent('smart_column_mapping', {
            'source_columns': parsed_data['columns'],
            'sample_data': parsed_data['sample_data'],
            'skip_calculated': True
        })
        logger.info(f"✅ Mapped {mapping_data.get('high_confidence_count', 0)} columns with high confidence")
        
        # ✅ FIXED Step 3.5: Extract mappings and confidence scores
        logger.info("📝 Step 3.5: Extracting confidence scores...")
        logger.info(f"🔍 DEBUG - mapping_data keys: {list(mapping_data.keys())}")
        
        # The mapping agent returns TWO separate dicts:
        # - mappings: {"source": "target"} (simple strings)
        # - confidence_scores: {"source": 0.94} (separate dict)
        simple_mappings = mapping_data.get('mappings', {})
        confidence_scores = mapping_data.get('confidence_scores', {})
        
        logger.info(f"🔍 DEBUG - simple_mappings count: {len(simple_mappings)}")
        logger.info(f"🔍 DEBUG - confidence_scores count: {len(confidence_scores)}")
        logger.info(f"🔍 DEBUG - confidence_scores: {confidence_scores}")
        
        # Log each mapping with its confidence
        for source_col, target_col in simple_mappings.items():
            conf = confidence_scores.get(source_col, 0.0)
            logger.info(f"   '{source_col}' → '{target_col}' = {conf:.2f}")
        
        logger.info(f"✅ Extracted {len(simple_mappings)} mappings with {len(confidence_scores)} confidence scores")
        
        # ✅ NEW: Check for completely unmappable files
        mappable_columns = [col for col, target in simple_mappings.items() if target is not None]
        
        if len(mappable_columns) == 0:
            logger.error(f"❌ UNMAPPABLE FILE - No columns could be mapped")
            logger.info(f"   All {len(simple_mappings)} columns have null mappings")
            logger.info(f"   Accuracy: {mapping_data.get('accuracy_estimate', 0)*100:.1f}%")
            
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': 'Unable to map file columns. Your file columns do not match any expected columns in the system.',
                    'error_type': 'unmappable_columns',
                    'details': {
                        'total_columns': len(simple_mappings),
                        'mappable_columns': 0,
                        'accuracy': mapping_data.get('accuracy_estimate', 0),
                        'source_columns': list(simple_mappings.keys())[:10],
                        'suggestion': 'Please check that your file contains the correct column headers. Contact support if you need help with the expected format.'
                    }
                })
            }
        
        logger.info(f"✅ Mappable columns: {len(mappable_columns)}/{len(simple_mappings)}")
        
        # Step 4: Transform data
        logger.info("📝 Step 4: Transforming data...")
        transform_result = invoke_mapping_agent('transform_data', {
            'source_data': parsed_data['full_data'],
            'mappings': simple_mappings
        })
        
        if isinstance(transform_result.get('transformed_data'), str):
            transformed_data_list = json.loads(transform_result['transformed_data'])
        else:
            transformed_data_list = transform_result.get('transformed_data', [])
        
        logger.info(f"✅ Transformed {len(transformed_data_list)} rows")
        
        # Step 5: Merge dates with transformed data
        logger.info("📝 Step 5: Merging dates with transformed data...")
        merged_rows = []

        # ✅ FIX: Handle case where transform produced 0 columns (all mappings null)
        if len(transformed_data_list) == 0:
            logger.warning("⚠️ Transformation produced 0 columns (all mappings null)")
            logger.info("   Creating merged rows with dates only...")
            for date_row in rows_with_dates:
                merged_rows.append({
                    'date': date_row['date'],
                    'date_formatted': date_row.get('date_formatted', date_row['date']),
                    'row_data': {}  # Empty data
                })
        else:
            # Normal merge
            for i, date_row in enumerate(rows_with_dates):
                if i < len(transformed_data_list):
                    merged_rows.append({
                        'date': date_row['date'],
                        'date_formatted': date_row.get('date_formatted', date_row['date']),
                        'row_data': transformed_data_list[i]
                    })

        logger.info(f"✅ Merged {len(merged_rows)} rows")
        
        # Step 6: Preview cell changes
        logger.info("📝 Step 6: Previewing cell changes...")
        preview_result = invoke_sheets_agent('preview_cell_changes', {
            'sheet_id': sheet_id,
            'sheet_name': 'DATA ENTRY',
            'date_column_name': 'Date',
            'rows_with_dates': merged_rows
        }, google_credentials)

        # Validation: Check if any dates matched
        matched_count = preview_result.get('matched_count', 0)
        total_dates = len(merged_rows)
        
        logger.info(f"\n🔍 Date Matching Validation:")
        logger.info(f"   Total dates in file: {total_dates}")
        logger.info(f"   Matched in Google Sheet: {matched_count}")

        if matched_count == 0:
            unmatched_dates = preview_result.get('unmatched_dates', [])
            logger.error(f"   ❌ ZERO MATCHES - Rejecting file")
            
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': f'No matching dates found. Your file contains {total_dates} dates, but none of them exist in the Google Sheet.',
                    'error_type': 'zero_date_matches',
                    'details': {
                        'total_file_dates': total_dates,
                        'matched_dates': 0,
                        'sample_file_dates': unmatched_dates[:10]
                    }
                })
            }
        
        logger.info(f"   ✅ Validation passed: {matched_count}/{total_dates} dates matched")
        
        # ✅ FIXED: Return response WITH confidence_scores
        response_body = {
            'success': True,
            'preview': {
                'mappings': simple_mappings,
                'confidence_scores': confidence_scores,
                'columns_mapped': len(simple_mappings),
                'high_confidence_count': mapping_data.get('high_confidence_count', 0),
                'needs_review': mapping_data.get('needs_review', []),
                'preview_rows': preview_result.get('preview_rows', []),
                'matched_dates': preview_result.get('matched_dates', []),
                'unmatched_dates': preview_result.get('unmatched_dates', []),
                'total_changes': preview_result.get('total_changes', 0),
                'cells_to_update': preview_result.get('cells_to_update', 0),
                'matched_count': matched_count,
                'unmatched_count': preview_result.get('unmatched_count', 0)
            }
        }
        
        # ✅ DEBUG: Log what we're sending back
        logger.info(f"📤 Response preview.confidence_scores: {confidence_scores}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        logger.error(f"❌ Preview workflow error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }


def handle_process_workflow(body):
    """Process workflow - actually updates Google Sheets"""
    try:
        logger.info("🚀 Starting PROCESS workflow...")
        
        file_data = body.get('file_data')
        target_sheet_url = body.get('target_sheet_url')
        google_credentials = body.get('google_credentials')
        approved_mappings = body.get('approved_mappings')
        
        if not all([file_data, target_sheet_url, google_credentials]):
            raise ValueError("Missing required fields")
        
        if approved_mappings:
            logger.info(f"✅ User provided approved mappings: {len(approved_mappings)} columns")
            logger.info(f"   Approved columns: {list(approved_mappings.keys())}")
        else:
            logger.info(f"ℹ️ No approved mappings, will use AI smart mapping")
        
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', target_sheet_url)
        if not match:
            raise ValueError("Invalid Google Sheets URL")
        
        sheet_id = match.group(1)
        logger.info(f"📄 Sheet ID: {sheet_id}")
        
        logger.info("📝 Step 0: Validating file type...")
        file_type, validation_error = detect_and_validate_file_type(file_data)
        
        if validation_error:
            logger.error(f"❌ File validation failed: {validation_error}")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': validation_error
                })
            }
        
        logger.info(f"✅ File type validated: {file_type.upper()}")
        
        logger.info(f"📝 Step 1: Parsing {file_type.upper()} file...")
        sheet_name = None if file_type == 'csv' else 0
        
        parsed_data = invoke_mapping_agent('parse_file', {
            'file_content': file_data,
            'file_type': file_type,
            'sheet_name': sheet_name
        })
        logger.info(f"✅ Parsed: {parsed_data.get('row_count', 0)} rows")
        
        logger.info("📝 Step 2: Extracting dates...")
        dates_data = invoke_mapping_agent('extract_dates_from_all_rows', {
            'data': parsed_data['full_data'],
            'date_column_name': 'Date'
        })
        rows_with_dates = dates_data.get('rows_with_dates', [])
        logger.info(f"✅ Extracted {len(rows_with_dates)} dates")
        
        if not rows_with_dates:
            logger.warning("⚠️ No dates extracted from file")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': 'No dates found in the uploaded file',
                    'rows_updated': 0
                })
            }
        
        simple_mappings = {}
        
        if approved_mappings:
            logger.info("📝 Step 3: Using user-approved column mappings...")
            simple_mappings = approved_mappings
            high_confidence_count = len(approved_mappings)
            logger.info(f"✅ Using {len(approved_mappings)} user-approved mappings")
        else:
            logger.info("📝 Step 3: AI smart column mapping...")
            mapping_data = invoke_mapping_agent('smart_column_mapping', {
                'source_columns': parsed_data['columns'],
                'sample_data': parsed_data['sample_data'],
                'skip_calculated': True
            })
            logger.info(f"✅ AI mapped {mapping_data.get('high_confidence_count', 0)} columns")
            
            for source_col, mapping_info in mapping_data['mappings'].items():
                if isinstance(mapping_info, dict):
                    simple_mappings[source_col] = mapping_info.get('target')
                else:
                    simple_mappings[source_col] = mapping_info
            
            high_confidence_count = mapping_data.get('high_confidence_count', 0)
        
        if not simple_mappings or len(simple_mappings) == 0:
            logger.warning("⚠️ No column mappings found")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': 'No columns could be mapped between source and target',
                    'rows_updated': 0
                })
            }
        
        logger.info("📝 Step 4: Transforming data...")
        transform_result = invoke_mapping_agent('transform_data', {
            'source_data': parsed_data['full_data'],
            'mappings': simple_mappings
        })
        
        if isinstance(transform_result.get('transformed_data'), str):
            transformed_data_list = json.loads(transform_result['transformed_data'])
        else:
            transformed_data_list = transform_result.get('transformed_data', [])
        
        logger.info(f"✅ Transformed {len(transformed_data_list)} rows")
        
        if not transformed_data_list:
            logger.warning("⚠️ Transformation produced no data")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': 'Data transformation failed - no data to update',
                    'rows_updated': 0
                })
            }
        
        logger.info("📝 Step 5: Merging dates with data...")
        merged_rows = []
        for i, date_row in enumerate(rows_with_dates):
            if i < len(transformed_data_list):
                merged_rows.append({
                    'date': date_row['date'],
                    'date_formatted': date_row.get('date_formatted', date_row['date']),
                    'row_data': transformed_data_list[i]
                })
        
        logger.info(f"✅ Prepared {len(merged_rows)} rows for update")
        
        if not merged_rows:
            logger.warning("⚠️ No rows to update after merging")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': 'No data to update after processing',
                    'rows_updated': 0
                })
            }
        
        logger.info("📝 Step 6: Updating Google Sheets...")
        update_result = invoke_sheets_agent('update_rows_by_date', {
            'sheet_id': sheet_id,
            'sheet_name': 'DATA ENTRY',
            'date_column_name': 'Date',
            'rows_with_dates': merged_rows
        }, google_credentials)
        
        rows_updated = update_result.get('rows_updated', 0)
        logger.info(f"✅ Updated {rows_updated} rows")
        
        if approved_mappings:
            logger.info(f"   └─ Used {len(approved_mappings)} user-approved columns")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'message': 'OPR processing complete',
                'rows_updated': rows_updated,
                'results': {
                    'rows_parsed': parsed_data['row_count'],
                    'columns_mapped': len(simple_mappings),
                    'high_confidence': high_confidence_count,
                    'rows_updated': rows_updated,
                    'cells_updated': update_result.get('cells_updated', 0),
                    'matched_dates': len(update_result.get('matched_dates', [])),
                    'unmatched_dates': len(update_result.get('unmatched_dates', [])),
                    'used_approved_mappings': approved_mappings is not None
                }
            })
        }
        
    except Exception as e:
        logger.error(f"❌ Process workflow error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }