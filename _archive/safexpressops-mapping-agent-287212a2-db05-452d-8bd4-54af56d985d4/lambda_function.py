import json

def lambda_handler(event, context):
    try:
        print(f"Mapping Agent received event keys: {list(event.keys())}")

        if 'body' in event and 'tool' not in event:
            body = event['body']
            if isinstance(body, str):
                body = json.loads(body)
        else:
            body = event

        tool_name = body.get('tool')
        inputs = body.get('inputs', {})

        if not tool_name:
            return {'success': False, 'error': 'Missing tool name'}

        from mapping_agent_api import (
            parse_file,
            smart_column_mapping,
            transform_data,
            extract_dates_from_all_rows,
            merge_dates_and_transformed_data,
            structure_target_data,
            structure_source_data,
            find_identifier,
            detect_source_sections,
            detect_source_sheets,
            detect_target_tab_overlap,
        )

        TOOL_REGISTRY = {
            'parse_file':                      parse_file,
            'smart_column_mapping':            smart_column_mapping,
            'transform_data':                  transform_data,
            'extract_dates_from_all_rows':     extract_dates_from_all_rows,
            'merge_dates_and_transformed_data': merge_dates_and_transformed_data,
            'structure_target_data':           structure_target_data,
            'structure_source_data':           structure_source_data,
            'find_identifier':                 find_identifier,
            'detect_source_sections':          detect_source_sections,
            'detect_source_sheets':            detect_source_sheets,
            'detect_target_tab_overlap':       detect_target_tab_overlap,
        }

        tool_func = TOOL_REGISTRY.get(tool_name)
        if not tool_func:
            return {'success': False, 'error': f'Unknown tool: {tool_name}'}

        print(f"Executing tool: {tool_name} with inputs: {list(inputs.keys())}")
        result = tool_func(**inputs)
        print(f"Tool completed: {tool_name}, success={result.get('success')}")
        return result

    except Exception as e:
        print(f"lambda_handler error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}