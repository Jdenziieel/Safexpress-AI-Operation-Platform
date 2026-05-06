import json
import base64
import os
import tempfile
import asyncio
from abc_analysis_agent_api import analyze_excel_and_upload_optimized, CredentialsDict


def lambda_handler(event, context):
    try:
        print(f"📥 ABC Agent received event keys: {list(event.keys())}")

        # Extract fields directly from event (wrapper sends flat payload)
        file_data = event.get('file_data')
        credentials_dict_raw = event.get('credentials_dict')
        date_column = event.get('date_column', 'Transdate')
        item_column = event.get('item_column', 'Itemcode')
        quantity_column = event.get('quantity_column', 'Qtyordered')
        description_column = event.get('description_column', 'Description')
        uom_column = event.get('uom_column', 'Qtyuom')
        a_threshold = float(event.get('a_threshold', 70.0))
        b_threshold = float(event.get('b_threshold', 90.0))

        if not file_data:
            return {'success': False, 'error': 'Missing file_data'}

        # Decode base64 and write to /tmp
        print("📂 Decoding base64 file...")
        file_bytes = base64.b64decode(file_data)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx', dir='/tmp') as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name
        print(f"   ✅ Written to {tmp_path} ({len(file_bytes):,} bytes)")

        # Build credentials object
        credentials = None
        if credentials_dict_raw:
            credentials = CredentialsDict(
                access_token=credentials_dict_raw.get('access_token', ''),
                refresh_token=credentials_dict_raw.get('refresh_token', ''),
                client_id=credentials_dict_raw.get('client_id'),
                client_secret=credentials_dict_raw.get('client_secret'),
            )

        # Run async analysis
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                analyze_excel_and_upload_optimized(
                    file_path=tmp_path,
                    credentials_dict=credentials,
                    date_column=date_column,
                    item_column=item_column,
                    quantity_column=quantity_column,
                    description_column=description_column,
                    uom_column=uom_column,
                    a_threshold=a_threshold,
                    b_threshold=b_threshold,
                )
            )
        finally:
            loop.close()
            try:
                os.unlink(tmp_path)
                print("🗑️ Temp file cleaned up")
            except Exception:
                pass

        return result

    except Exception as e:
        print(f"❌ lambda_handler error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}