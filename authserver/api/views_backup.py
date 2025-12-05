from django.shortcuts import redirect
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from allauth.socialaccount.models import SocialToken, SocialAccount
from .serializers import UserSerializer
import json
import os
import requests
import re
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class UserCreate(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]


class UserDetailView(generics.RetrieveUpdateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


@login_required
def google_login_callback(request):
    user = request.user
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    social_accounts = SocialAccount.objects.filter(user=user)
    print("Social Account for user:", social_accounts)
    social_account = social_accounts.first()

    if not social_account:
        print("No social account for user:", user)
        return redirect(f"{FRONTEND_URL}/login/callback/?error=NoSocialAccount")

    token = SocialToken.objects.filter(
        account=social_account, account__provider="google"
    ).first()

    if token:
        print("Google token found", token.token)
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        return redirect(f"{FRONTEND_URL}/login/callback/?access_token={access_token}")
    else:
        print("No google token found for user", user)
        return redirect(f"{FRONTEND_URL}/login/callback/?error=NoGoogleToken")


@csrf_exempt
def validate_google_token(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            google_access_token = data.get("access_token")
            print(google_access_token)

            if not google_access_token:
                return JsonResponse({"detail": "Access token is missing."}, status=400)
            return JsonResponse({"valid": True})
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON."}, status=400)
    return JsonResponse({"detail": "Method not allowed"}, status=405)


@csrf_exempt
def google_auth_dynamodb(request):
    """Handle Google OAuth authentication"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            auth_code = data.get("code")

            if not auth_code:
                return JsonResponse(
                    {"error": "Authorization code is missing."}, status=400
                )

            print(f"Received auth code: {auth_code[:20]}...")

            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                "code": auth_code,
                "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
                "redirect_uri": "postmessage",
                "grant_type": "authorization_code",
            }

            token_response = requests.post(token_url, data=token_data)
            token_response_data = token_response.json()

            print(f"Token exchange response: {token_response_data}")

            if "error" in token_response_data:
                return JsonResponse(
                    {
                        "error": token_response_data.get(
                            "error_description", token_response_data["error"]
                        )
                    },
                    status=400,
                )

            access_token = token_response_data.get("access_token")

            if not access_token:
                return JsonResponse(
                    {"error": "No access token received from Google"}, status=400
                )

            userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            userinfo_response = requests.get(userinfo_url, headers=headers)
            userinfo = userinfo_response.json()

            print(f"User info: {userinfo}")

            email = userinfo.get("email")
            name = userinfo.get("name", "")
            google_id = userinfo.get("id")
            picture = userinfo.get("picture", "")

            if not email:
                return JsonResponse(
                    {"error": "Email not provided by Google"}, status=400
                )

            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": email.split("@")[0],
                    "first_name": name.split()[0] if name else "",
                    "last_name": (
                        " ".join(name.split()[1:])
                        if name and len(name.split()) > 1
                        else ""
                    ),
                },
            )

            print(f"User {'created' if created else 'found'}: {user.email}")

            from allauth.socialaccount.models import (
                SocialAccount,
                SocialToken,
                SocialApp,
            )

            social_app, created = SocialApp.objects.get_or_create(
                provider="google",
                defaults={
                    "name": "Google",
                    "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
                    "secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
                },
            )

            social_account, created = SocialAccount.objects.get_or_create(
                user=user,
                provider="google",
                defaults={
                    "uid": google_id,
                    "extra_data": userinfo,
                },
            )

            social_token, created = SocialToken.objects.get_or_create(
                account=social_account,
                app=social_app,
                defaults={
                    "token": access_token,
                    "token_secret": token_response_data.get("refresh_token", ""),
                    "expires_at": timezone.now()
                    + timedelta(seconds=token_response_data.get("expires_in", 3600)),
                },
            )

            print(f"✅ Created/updated SocialAccount and SocialToken for {user.email}")
            print(f"   Access token: {access_token[:20]}...")
            print(
                f"   Refresh token: {token_response_data.get('refresh_token', 'None')[:20]}..."
            )

            refresh = RefreshToken.for_user(user)
            access_token_jwt = str(refresh.access_token)

            return JsonResponse(
                {
                    "access": access_token_jwt,
                    "refresh": str(refresh),
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "name": name,
                        "picture": picture,
                    },
                },
                status=200,
            )

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON."}, status=400)
        except Exception as e:
            import traceback

            print(f"Error in google_auth_dynamodb: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse(
                {"error": f"Authentication failed: {str(e)}"}, status=500
            )

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def dynamic_mapping_workflow(request):
    """
    Complete workflow with human-in-the-loop check for existing data
    """
    try:
        file = request.FILES.get("file")
        sheet_id = request.data.get("target_url")
        force_upload = request.data.get("force_upload", "false").lower() == "true"

        if not file:
            return JsonResponse({"error": "No file uploaded"}, status=400)

        if not sheet_id:
            return JsonResponse({"error": "Sheet ID is required"}, status=400)

        sheet_id = sheet_id.strip()
        print(f"🔍 Received Sheet ID: {sheet_id}")

        if len(sheet_id) != 44:
            return JsonResponse(
                {
                    "error": f"Invalid sheet ID format (expected 44 characters, got {len(sheet_id)})"
                },
                status=400,
            )

        # ============================================
        # GET USER CREDENTIALS FIRST
        # ============================================
        from allauth.socialaccount.models import SocialToken, SocialAccount

        social_account = SocialAccount.objects.filter(
            user=request.user, provider="google"
        ).first()

        if not social_account:
            return JsonResponse(
                {
                    "error": "No Google account linked. Please connect your Google account first"
                },
                status=400,
            )

        google_token = SocialToken.objects.filter(account=social_account).first()

        if not google_token:
            return JsonResponse(
                {"error": "No Google token found. Please re-authenticate"},
                status=400,
            )

        user_google_credentials = {
            "access_token": google_token.token or "",
            "refresh_token": google_token.token_secret or "",
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
        }

        # ============================================
        # STEP 1: Parse file
        # ============================================
        file_type = "xlsx" if file.name.endswith(".xlsx") else "csv"

        if file_type == "xlsx":
            import base64
            file_content = base64.b64encode(file.read()).decode("utf-8")
        else:
            file_content = file.read().decode("utf-8")

        print(f"Processing file: {file.name} ({file_type})")
        print("Step 1: Parsing file...")

        parse_response = requests.post(
            "http://localhost:8004/execute_task",
            json={
                "tool": "parse_file",
                "inputs": {"file_content": file_content, "file_type": file_type},
            },
        )

        if parse_response.status_code != 200:
            return JsonResponse({"error": "File parsing failed"}, status=500)

        parse_result = parse_response.json()
        if not parse_result.get("success"):
            return JsonResponse(
                {"error": parse_result.get("error", "Parse failed")}, status=500
            )

        columns = parse_result["result"]["columns"]
        full_data = parse_result["result"]["full_data"]

        print(
            f"   ✅ Parsed {len(columns)} columns, {parse_result['result']['row_count']} rows"
        )

        # Extract dates from parsed data
        parsed_data = json.loads(full_data)
        upload_dates = [row.get("Date") for row in parsed_data if row.get("Date")]

        # ============================================
        # STEP 2: Smart column mapping
        # ============================================
        print("Step 2: Smart column mapping...")
        map_response = requests.post(
            "http://localhost:8004/execute_task",
            json={
                "tool": "smart_column_mapping",
                "inputs": {"source_columns": columns, "skip_calculated": True},
            },
        )

        if map_response.status_code != 200:
            return JsonResponse({"error": "Column mapping failed"}, status=500)

        map_result = map_response.json()
        if not map_result.get("success"):
            return JsonResponse(
                {"error": map_result.get("error", "Mapping failed")}, status=500
            )

        mappings = map_result["result"]["mappings"]
        print(f"   ✅ Mapped {map_result['result']['high_confidence_count']} columns")

        # ============================================
        # STEP 3: Check for existing data
        # ============================================
        if not force_upload and upload_dates:
            print(f"Step 3: Checking for existing data...")

            # Define mapped_columns before use
            mapped_columns = [target_col for target_col in mappings.values() if target_col]

            try:
                # ============================================
                # PHASE 1: Quick check - Does sheet have ANY data?
                # ============================================
                print(f"   Phase 1: Quick check if sheet has any data...")
                quick_check = requests.post(
                    "http://localhost:8003/execute_task",
                    json={
                        "tool": "check_sheet_has_data",
                        "inputs": {
                            "sheet_id": sheet_id,
                            "sheet_name": "DATA ENTRY",
                        },
                        "credentials_dict": user_google_credentials,
                    },
                )

                if quick_check.status_code == 200:
                    quick_result = quick_check.json()
                    if quick_result.get("success"):
                        has_any_data = quick_result.get("result", {}).get("has_data", False)
                        
                        if not has_any_data:
                            # ✅ Sheet is empty, safe to proceed
                            print(f"   ✅ Sheet is empty (only headers), safe to proceed")
                            return JsonResponse({
                                "requires_confirmation": True,
                                "confirmation_type": "safe",
                                "conflict_data": {
                                    "total_conflicts": 0,
                                    "total_safe": len(upload_dates),
                                    "safe_dates": upload_dates[:10],
                                    "mapped_columns": mapped_columns[:10],
                                },
                                "message": (
                                    f"📋 Upload Confirmation\n\n"
                                    f"You are uploading data for {len(upload_dates)} dates "
                                    f"(e.g., {', '.join([str(d) for d in upload_dates[:3]])})...\n\n"
                                    f"✅ These dates have NO operational data - completely safe.\n\n"
                                    f"Proceed with upload?"
                                ),
                            }, status=200)
                        else:
                            # ⚠️ Sheet has data - check which dates
                            print(f"   ⚠️ Sheet has operational data for some dates")
                            check_response = requests.post(
                                "http://localhost:8003/execute_task",
                                json={
                                    "tool": "check_dates_have_data",
                                    "inputs": {
                                        "sheet_id": sheet_id,
                                        "dates_to_check": upload_dates,
                                        "sheet_name": "DATA ENTRY",
                                    },
                                    "credentials_dict": user_google_credentials,
                                },
                            )
                            
                            if check_response.status_code == 200:
                                check_result = check_response.json()
                                if check_result.get("success"):
                                    result_data = check_result.get("result", {})
                                    conflicting_rows = result_data.get("conflicting_rows", [])
                                    dates_with_data = result_data.get("dates_with_data", [])
                                    dates_without_data = result_data.get("dates_without_data", [])
                                    
                                    if len(conflicting_rows) > 0:
                                        # DATES HAVE OPERATIONAL DATA - Show warning
                                        print(f"      ⚠️ {len(conflicting_rows)} dates already have operational data!")
                                        return JsonResponse({
                                            "requires_confirmation": True,
                                            "confirmation_type": "overwrite",
                                            "conflict_data": {
                                                "total_conflicts": len(conflicting_rows),
                                                "total_safe": len(dates_without_data),
                                                "conflicting_dates": dates_with_data[:10],
                                                "safe_dates": dates_without_data[:5],
                                                "sample_conflicts": conflicting_rows[:5],
                                                "mapped_columns": mapped_columns[:10],
                                            },
                                            "message": (
                                                f"⚠️ WARNING: {len(conflicting_rows)} out of {len(upload_dates)} dates "
                                                f"already have operational data!\n\n"
                                                f"Dates with existing data: {', '.join([str(d) for d in dates_with_data[:5]])}...\n\n"
                                                f"You are uploading: {', '.join(mapped_columns[:5])}...\n\n"
                                                f"⚠️ This will ADD data to rows that already contain operational data.\n\n"
                                                f"Proceed?"
                                            ),
                                        }, status=200)
                                    else:
                                        # Safe - no operational data in these dates
                                        print(f"      ✅ All {len(upload_dates)} dates are safe (no operational data)")
                                        return JsonResponse({
                                            "requires_confirmation": True,
                                            "confirmation_type": "safe",
                                            "conflict_data": {
                                                "total_conflicts": 0,
                                                "total_safe": len(upload_dates),
                                                "safe_dates": upload_dates[:10],
                                                "mapped_columns": mapped_columns[:10],
                                            },
                                            "message": (
                                                f"📋 Upload Confirmation\n\n"
                                                f"You are uploading data for {len(upload_dates)} dates "
                                                f"(e.g., {', '.join([str(d) for d in upload_dates[:3]])})...\n\n"
                                                f"✅ These dates have NO operational data - completely safe.\n\n"
                                                f"Proceed with upload?"
                                            ),
                                        }, status=200)
            except Exception as e:
                print(f"⚠️  Could not check for existing data: {str(e)}")
                import traceback
                traceback.print_exc()
                # Continue with upload if check fails

        # ============================================
        # STEP 4: Transform data
        # ============================================
        print("Step 4: Transforming data...")
        transform_response = requests.post(
            "http://localhost:8004/execute_task",
            json={
                "tool": "transform_data",
                "inputs": {"source_data": full_data, "mappings": mappings},
            },
        )

        if transform_response.status_code != 200:
            return JsonResponse({"error": "Data transformation failed"}, status=500)

        transform_result = transform_response.json()
        if not transform_result.get("success"):
            return JsonResponse(
                {"error": transform_result.get("error", "Transform failed")}, status=500
            )

        transformed_data = transform_result["result"]["transformed_data"]
        print(f"   ✅ Transformed {transform_result['result']['row_count']} rows")

        # Build rows_with_dates
        rows_with_dates = [
            {"date": row.get("Date"), "row_index": i}
            for i, row in enumerate(parsed_data)
            if row.get("Date")
        ]

        # ============================================
        # STEP 5: Upload to Sheets
        # ============================================
        print("Step 5: Uploading to Google Sheets...")

        upload_response = requests.post(
            "http://localhost:8003/execute_task",
            json={
                "tool": "update_by_date_match",
                "inputs": {
                    "sheet_id": sheet_id,
                    "transformed_data": transformed_data,
                    "rows_with_dates": rows_with_dates,
                    "sheet_name": "DATA ENTRY",
                    "date_column": "Date",
                },
                "credentials_dict": user_google_credentials,
            },
        )

        if upload_response.status_code != 200:
            return JsonResponse(
                {"error": f"Sheets upload failed: {upload_response.text}"}, status=500
            )

        upload_result = upload_response.json()

        if not upload_result.get("success"):
            return JsonResponse(
                {"error": upload_result.get("error", "Upload failed")}, status=500
            )

        result_data = upload_result.get("result", {})
        rows_updated = result_data.get("rows_updated", 0)

        print(f"   ✅ Updated {rows_updated} rows in Google Sheets")

        return JsonResponse(
            {
                "success": True,
                "message": f"Successfully updated {rows_updated} rows",
                "details": {
                    "file_name": file.name,
                    "rows_uploaded": rows_updated,
                    "columns_mapped": len([m for m in mappings.values() if m]),
                    "high_confidence_mappings": map_result["result"][
                        "high_confidence_count"
                    ],
                    "sheet_id": sheet_id,
                },
            },
            status=200,
        )

    except Exception as e:
        import traceback

        print(f"❌ Error in dynamic_mapping_workflow: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({"error": f"Workflow failed: {str(e)}"}, status=500)
