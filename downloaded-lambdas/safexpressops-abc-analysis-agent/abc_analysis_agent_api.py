"""
ABC Analysis Agent API - Lambda Compatible Version
"""

import json
from pydantic import BaseModel
from typing import Dict, Any, Optional
import pandas as pd
from datetime import datetime
import os
import time
from functools import wraps
import asyncio
from concurrent.futures import ThreadPoolExecutor
import numpy as np


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


# Thread pool for CPU-bound operations
executor = ThreadPoolExecutor(max_workers=4)


class CredentialsDict(BaseModel):
    """Google OAuth credentials"""
    access_token: str
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


def monitor_task(agent_name: str, task_type: str):
    """Simple monitoring decorator"""
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    elapsed = time.time() - start_time
                    print(f"📊 {task_type} completed in {elapsed:.2f}s")
                    return result
                except Exception as e:
                    print(f"❌ {task_type} failed: {str(e)}")
                    raise
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    elapsed = time.time() - start_time
                    print(f"📊 {task_type} completed in {elapsed:.2f}s")
                    return result
                except Exception as e:
                    print(f"❌ {task_type} failed: {str(e)}")
                    raise
            return sync_wrapper
    return decorator


class OptimizedMonthlyABCAnalysisEngine:
    """Performance-optimized ABC analysis engine"""

    def __init__(self, a_threshold: float = 70.0, b_threshold: float = 90.0):
        self.a_threshold = a_threshold
        self.b_threshold = b_threshold
        print(f"🎯 ABC Engine initialized: A≤{a_threshold}%, B≤{b_threshold}%, C>{b_threshold}%")

    def detect_months(self, df: pd.DataFrame, date_column: str = "Transdate") -> Dict[str, pd.DataFrame]:
        """Detect months using vectorized operations"""
        print(f"\n📅 AUTO-DETECTING MONTHS from column: {date_column}")

        if date_column not in df.columns:
            print(f"❌ Date column '{date_column}' not found! Available: {list(df.columns)}")
            return {}

        df["_year_month"] = df[date_column].dt.to_period("M")
        month_data = {}

        for period, group_df in df.groupby("_year_month", sort=False):
            month_date = period.to_timestamp()
            month_key = month_date.strftime("%b %Y")
            print(f"   ✓ {month_key}: {len(group_df):,} transactions")
            month_data[month_key] = group_df.drop(columns=["_year_month"]).copy()

        df.drop(columns=["_year_month"], inplace=True)
        return month_data

    def perform_abc_analysis_optimized(
        self,
        df: pd.DataFrame,
        item_col: str,
        quantity_col: str,
        description_col: str = None,
        uom_col: str = None,
        label: str = "Analysis",
    ) -> tuple:
        """Fully vectorized ABC analysis"""
        print(f"\n📊 ABC Analysis: {label}")

        group_cols = [item_col]
        if description_col and description_col in df.columns:
            group_cols.append(description_col)
        if uom_col and uom_col in df.columns:
            group_cols.append(uom_col)

        agg = (
            df.groupby(group_cols, sort=False)
            .agg({quantity_col: ["sum", "count"]})
            .reset_index()
        )

        agg.columns = group_cols + ["Total_Qty", "Order_Count"]
        agg["Item_Score"] = agg["Total_Qty"] * agg["Order_Count"]

        agg.sort_values("Item_Score", ascending=False, inplace=True)
        agg.reset_index(drop=True, inplace=True)

        total_score = agg["Item_Score"].sum()
        agg["Percentage"] = ((agg["Item_Score"] / total_score) * 101).round(2)
        agg["Cumulative_Pct"] = agg["Percentage"].cumsum().round(2)

        agg["ABC_Class"] = np.where(
            agg["Cumulative_Pct"] <= self.a_threshold,
            "A",
            np.where(agg["Cumulative_Pct"] <= self.b_threshold, "B", "C"),
        )

        agg.insert(0, "Rank", range(1, len(agg) + 1))
        summary = self._generate_summary_optimized(agg)

        print(f"   Class A: {summary['class_A']['item_count']} items ({summary['class_A']['contribution_pct']}%)")
        print(f"   Class B: {summary['class_B']['item_count']} items ({summary['class_B']['contribution_pct']}%)")
        print(f"   Class C: {summary['class_C']['item_count']} items ({summary['class_C']['contribution_pct']}%)")

        return agg, summary

    def _generate_summary_optimized(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate summary using vectorized groupby"""
        summary = {}
        total_items = len(df)

        grouped = df.groupby("ABC_Class").agg({
            "Total_Qty": ["sum", "mean"],
            "Order_Count": ["sum", "mean"],
            "Percentage": "sum",
        })

        for abc_class in ["A", "B", "C"]:
            if abc_class in grouped.index:
                row = grouped.loc[abc_class]
                count = len(df[df["ABC_Class"] == abc_class])
                summary[f"class_{abc_class}"] = {
                    "item_count": count,
                    "pct_of_items": round(count / total_items * 100, 1) if total_items > 0 else 0,
                    "total_quantity": int(row[("Total_Qty", "sum")]),
                    "total_orders": int(row[("Order_Count", "sum")]),
                    "contribution_pct": round(row[("Percentage", "sum")], 1),
                }
            else:
                summary[f"class_{abc_class}"] = {
                    "item_count": 0, "pct_of_items": 0, "total_quantity": 0,
                    "total_orders": 0, "contribution_pct": 0,
                }
        return summary

    async def analyze_all_months_parallel(
        self,
        month_data: Dict[str, pd.DataFrame],
        item_col: str,
        quantity_col: str,
        description_col: str = None,
        uom_col: str = None,
    ) -> Dict[str, Any]:
        """Parallel processing of multiple months"""
        print("\n📈 ANALYZING ALL MONTHS")

        loop = asyncio.get_event_loop()

        async def analyze_month(month_key: str, month_df: pd.DataFrame):
            results, summary = await loop.run_in_executor(
                executor,
                self.perform_abc_analysis_optimized,
                month_df, item_col, quantity_col, description_col, uom_col, month_key,
            )
            results["Month"] = month_key
            return month_key, {"results": results, "summary": summary, "transactions": len(month_df)}

        tasks = [analyze_month(mk, mdf) for mk, mdf in month_data.items()]
        results_list = await asyncio.gather(*tasks)

        return {mk: data for mk, data in results_list}


def create_sheets_package_optimized(monthly_results: Dict[str, Any], a_threshold: float, b_threshold: float) -> Dict[str, Any]:
    """Create sheets package for upload"""
    try:
        print("\n📦 Creating Sheets Package")

        sheets_dict = {}

        # Combine all monthly results
        all_items_list = []
        total_class_a = 0
        total_class_b = 0
        total_class_c = 0
        
        for month_key, data in monthly_results.items():
            df = data["results"].copy()
            df["Month"] = month_key
            all_items_list.append(df)
            
            # Sum up the class counts from monthly analysis
            total_class_a += data["summary"]["class_A"]["item_count"]
            total_class_b += data["summary"]["class_B"]["item_count"]
            total_class_c += data["summary"]["class_C"]["item_count"]

        all_items_df = pd.concat(all_items_list, ignore_index=True, copy=False)
        all_items_df.sort_values("Item_Score", ascending=False, inplace=True)
        all_items_df.reset_index(drop=True, inplace=True)
        all_items_df["Rank"] = range(1, len(all_items_df) + 1)

        total_transactions = sum(data["transactions"] for data in monthly_results.values())
        total_items = len(all_items_df)

        # Use the summed class counts from monthly analysis
        if len(monthly_results) == 1:
            month_key = list(monthly_results.keys())[0]
            total_class_a = monthly_results[month_key]["summary"]["class_A"]["item_count"]
            total_class_b = monthly_results[month_key]["summary"]["class_B"]["item_count"]
            total_class_c = monthly_results[month_key]["summary"]["class_C"]["item_count"]
            total_items = total_class_a + total_class_b + total_class_c

        # Calculate contribution percentages dynamically
        c_threshold = 100 - b_threshold
        b_contribution = b_threshold - a_threshold

        # Executive Summary
        pct_a = round((total_class_a / total_items * 100), 1) if total_items > 0 else 0
        pct_b = round((total_class_b / total_items * 100), 1) if total_items > 0 else 0
        pct_c = round((total_class_c / total_items * 100), 1) if total_items > 0 else 0
        
        exec_summary = [
            ["ABC ANALYSIS - EXECUTIVE SUMMARY"],
            [""],
            ["Total Transactions:", total_transactions],
            ["Total Unique Items:", total_items],
            ["Months Analyzed:", len(monthly_results)],
            [""],
            ["ABC CLASSIFICATION THRESHOLDS"],
            [f"Class A: Cumulative ≤ {a_threshold}%"],
            [f"Class B: Cumulative {a_threshold}% - {b_threshold}%"],
            [f"Class C: Cumulative > {b_threshold}%"],
            [""],
            ["ABC CLASSIFICATION SUMMARY"],
            ["Category", "Item Count", "% of Items", "Contribution %"],
            ["Class A (High Priority)", total_class_a, f"{pct_a}%", f"~{a_threshold}%"],
            ["Class B (Medium Priority)", total_class_b, f"{pct_b}%", f"~{b_contribution}%"],
            ["Class C (Low Priority)", total_class_c, f"{pct_c}%", f"~{c_threshold}%"],
        ]
        sheets_dict["Executive Summary"] = exec_summary

        # Monthly Comparison
        comparison_data = [
            ["MONTHLY ABC ANALYSIS COMPARISON"],
            [""],
            ["Month", "Transactions", "Total Items", "Class A", "Class B", "Class C"],
        ]
        for month_key in sorted(monthly_results.keys()):
            data = monthly_results[month_key]
            comparison_data.append([
                month_key, data["transactions"], len(data["results"]),
                data["summary"]["class_A"]["item_count"],
                data["summary"]["class_B"]["item_count"],
                data["summary"]["class_C"]["item_count"],
            ])
        sheets_dict["Monthly Comparison"] = comparison_data

        def df_to_list(df):
            return [df.columns.tolist()] + df.fillna("").values.tolist()

        sheets_dict["Complete ABC Analysis"] = df_to_list(all_items_df)

        for class_letter in ["A", "B", "C"]:
            class_df = all_items_df[all_items_df["ABC_Class"] == class_letter].copy()
            sheets_dict[f"Class {class_letter} Items"] = df_to_list(class_df)

        for month_key, data in monthly_results.items():
            safe_name = month_key.replace(" ", "_")[:30]
            sheets_dict[safe_name] = df_to_list(data["results"])

        print(f"   ✅ Created {len(sheets_dict)} sheets")
        
        return {
            "success": True, 
            "sheets_data": json.dumps(sheets_dict, cls=NumpyEncoder), 
            "sheet_count": len(sheets_dict),
            "total_items": total_items,
            "class_a_count": int(total_class_a),
            "class_b_count": int(total_class_b),
            "class_c_count": int(total_class_c),
            "a_threshold": a_threshold,
            "b_threshold": b_threshold,
        }

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@monitor_task("abc_agent", "analyze_excel_and_upload")
async def analyze_excel_and_upload_optimized(
    file_path: str,
    credentials_dict: Optional[CredentialsDict] = None,
    date_column: str = "Transdate",
    item_column: str = "Itemcode",
    quantity_column: str = "Qtyordered",
    description_column: str = "Description",
    uom_column: str = "Qtyuom",
    a_threshold: float = 70.0,
    b_threshold: float = 90.0,
) -> Dict[str, Any]:
    """Main analysis function"""
    if credentials_dict is None:
         print("🔐 No credentials provided, using Google OAuth from Secrets Manager")
         credentials_dict =  get_google_credentials_from_secrets()
    try:
        print("\n" + "=" * 60)
        print("🎯 STARTING ABC ANALYSIS")
        print(f"📊 Thresholds: A≤{a_threshold}%, B≤{b_threshold}%, C>{b_threshold}%")
        print("=" * 60)

        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(executor, pd.read_excel, file_path)

        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        df[date_column] = pd.to_datetime(df[date_column])

        print(f"   ✓ Loaded {len(df):,} rows, {len(df.columns)} columns")

        engine = OptimizedMonthlyABCAnalysisEngine(a_threshold=a_threshold, b_threshold=b_threshold)
        month_data = engine.detect_months(df, date_column)

        if not month_data:
            return {"success": False, "error": "No months detected in data"}

        monthly_results = await engine.analyze_all_months_parallel(
            month_data, item_column, quantity_column, description_column, uom_column
        )

        sheets_package = await loop.run_in_executor(
            executor, create_sheets_package_optimized, monthly_results, a_threshold, b_threshold
        )

        if not sheets_package["success"]:
            return sheets_package

        # Upload to Google Sheets via Lambda invocation
        print("\n📤 Uploading to Google Sheets...")

        import boto3
        lambda_client = boto3.client('lambda', region_name='ap-southeast-1')

        SHEETS_AGENT_ARN = os.environ.get("SHEETS_AGENT_ARN", "safexpressops-sheets-agent")
        print(f"   📞 Calling Sheets Agent: {SHEETS_AGENT_ARN}")

        months = sorted(month_data.keys())
        sheet_title = f"ABC Analysis - {months[0]} to {months[-1]}" if len(months) > 1 else f"ABC Analysis - {months[0]}"

        sheets_dict = json.loads(sheets_package["sheets_data"])
        sheet_names = list(sheets_dict.keys())

        # Create sheet via Lambda
        create_payload = {
            "tool": "create_sheet",
            "inputs": {"title": sheet_title, "sheet_names": sheet_names},
            "credentials_dict": credentials_dict.dict(),
        }

        create_response = lambda_client.invoke(
            FunctionName=SHEETS_AGENT_ARN,
            InvocationType='RequestResponse',
            Payload=json.dumps(create_payload, cls=NumpyEncoder)
        )

        create_result = json.loads(create_response['Payload'].read().decode('utf-8'))
        print(f"   📋 Create response: {create_result}")

        # Handle Lambda response format
        if 'body' in create_result:
            create_body = json.loads(create_result['body']) if isinstance(create_result['body'], str) else create_result['body']
        else:
            create_body = create_result

        if not create_body.get("success"):
            return {"success": False, "error": create_body.get("error", "Failed to create sheet")}

        # Get sheet info from result
        result_data = create_body.get("result", create_body)
        sheet_id = result_data.get("sheet_id")
        sheet_url = result_data.get("sheet_url")

        if not sheet_id:
            return {"success": False, "error": "No sheet_id in response"}

        print(f"   ✅ Created sheet: {sheet_url}")

        # Upload data via Lambda
        upload_payload = {
            "tool": "upload_multi_sheet_data",
            "inputs": {"sheet_id": sheet_id, "sheets_data": sheets_package["sheets_data"]},
            "credentials_dict": credentials_dict.dict(),
        }

        upload_response = lambda_client.invoke(
            FunctionName=SHEETS_AGENT_ARN,
            InvocationType='RequestResponse',
            Payload=json.dumps(upload_payload, cls=NumpyEncoder)
        )

        upload_result = json.loads(upload_response['Payload'].read().decode('utf-8'))
        print(f"   📋 Upload response: {upload_result}")

        if 'body' in upload_result:
            upload_body = json.loads(upload_result['body']) if isinstance(upload_result['body'], str) else upload_result['body']
        else:
            upload_body = upload_result

        if not upload_body.get("success"):
            return {"success": False, "error": upload_body.get("error", "Upload failed")}

        print(f"\n✅ SUCCESS! Sheet URL: {sheet_url}")

        # Return consistent data
        total_items = sheets_package.get("total_items", 0)
        class_a = sheets_package.get("class_a_count", 0)
        class_b = sheets_package.get("class_b_count", 0)
        class_c = sheets_package.get("class_c_count", 0)
        
        # Calculate dynamic contribution percentages
        c_contribution = 100 - b_threshold
        b_contribution = b_threshold - a_threshold
        
        return {
            "success": True,
            "sheet_url": sheet_url,
            "sheet_id": sheet_id,
            "total_transactions": len(df),
            "total_items": total_items,
            "class_a_count": class_a,
            "class_b_count": class_b,
            "class_c_count": class_c,
            "a_threshold": a_threshold,
            "b_threshold": b_threshold,
            "a_contribution": a_threshold,
            "b_contribution": b_contribution,
            "c_contribution": c_contribution,
            "months_analyzed": list(monthly_results.keys()),
            "monthly_summary": {
                month: {
                    "transactions": data["transactions"],
                    "total_items": len(data["results"]),
                    "class_a": data["summary"]["class_A"]["item_count"],
                    "class_b": data["summary"]["class_B"]["item_count"],
                    "class_c": data["summary"]["class_C"]["item_count"],
                }
                for month, data in monthly_results.items()
            },
        }

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
        
def get_google_credentials_from_secrets():
    """Get Google OAuth credentials from AWS Secrets Manager"""
    import os
    import boto3
    import json
    
    secrets_client = boto3.client('secretsmanager', region_name='ap-southeast-1')
    
    # Get the shared Google OAuth secret
    secret_name = os.environ.get('GOOGLE_OAUTH_SECRET', 'prod/app/google-oauth')
    
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response['SecretString'])
        
        print(f"✅ Retrieved Google OAuth credentials from Secrets Manager")
        
        # Return in expected format
        return CredentialsDict(
            access_token='',  # Not needed for service account
            refresh_token='',
            client_id=secret_data.get('GOOGLE_CLIENT_ID'),
            client_secret=secret_data.get('GOOGLE_CLIENT_SECRET')
        )
    except Exception as e:
        print(f"❌ Error getting Google credentials: {str(e)}")
        raise Exception("Failed to get Google OAuth credentials from Secrets Manager")