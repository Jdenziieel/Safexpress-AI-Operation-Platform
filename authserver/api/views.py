from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from allauth.socialaccount.models import SocialToken, SocialAccount
from .serializers import UserSerializer, OnboardUserSerializer
from .models import CustomUser, AdminActivityLog
import json
import os
import requests
import re
from django.utils import timezone
from datetime import datetime, timedelta
from django.conf import settings
from api.permissions import IsAdminUser

User = get_user_model()


def log_admin_activity(request, action, target_user, details=None):
    """
    Helper function to log admin activity.
    
    Args:
        request: The HTTP request object (to get admin info and IP)
        action: The action type (onboard, activate, deactivate, update_role, update_name, update)
        target_user: The CustomUser object being affected
        details: Optional dict with additional details
    """
    try:
        # Get client IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        
        AdminActivityLog.objects.create(
            admin_email=request.user.gmail,
            admin_name=request.user.fullname,
            action=action,
            target_user_email=target_user.gmail,
            target_user_name=target_user.fullname,
            details=json.dumps(details) if details else None,
            ip_address=ip_address
        )
        print(f"📝 Activity logged: {request.user.gmail} - {action} - {target_user.gmail}")
    except Exception as e:
        print(f"⚠️ Failed to log admin activity: {str(e)}")


class UserCreate(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]


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
    """
    Handle Google OAuth authentication with onboarding check.
    
    Flow:
    1. Exchange auth code for Google access token
    2. Get user info from Google
    3. Check if user is onboarded (exists in auth_user with is_active=True)
    4. If not onboarded, reject login
    5. If onboarded, create/update SocialAccount and SocialToken
    6. Return JWT tokens
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            auth_code = data.get("code")

            if not auth_code:
                return JsonResponse(
                    {"error": "Authorization code is missing."}, status=400
                )

            print(f"Received auth code: {auth_code[:20]}...")

            # Step 1: Exchange auth code for Google tokens
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

            # Step 2: Get user info from Google
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

            print(f"👤 Checking onboarding status for: {email}")

            # Step 3: Check if user is onboarded (exists and is_active=True)
            try:
                user = CustomUser.objects.get(gmail=email)
                
                # Check if user is active (onboarded)
                if not user.is_active:
                    print(f"❌ User {email} exists but is not onboarded (is_active=False)")
                    return JsonResponse(
                        {
                            "error": "Account not activated",
                            "message": "Your account has not been onboarded yet. Please contact an administrator to activate your account.",
                            "email": email
                        },
                        status=403
                    )
                
                print(f"✅ Found onboarded user: {user.gmail}")
                
                # Update picture if available
                if picture and user.google_picture != picture:
                    user.google_picture = picture
                    user.save(update_fields=["google_picture", "updated_at"])
                    
            except CustomUser.DoesNotExist:
                # User not found - not onboarded
                print(f"❌ User {email} not found in database - not onboarded")
                return JsonResponse(
                    {
                        "error": "Account not found",
                        "message": "Your account has not been onboarded yet. Please contact an administrator to create your account.",
                        "email": email
                    },
                    status=403
                )

            # Step 4: Create/update SocialAccount and SocialToken
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

            # Update extra_data if account already exists
            if not created:
                social_account.extra_data = userinfo
                social_account.save()

            refresh_token = token_response_data.get("refresh_token", "")
            try:
                social_token = SocialToken.objects.get(
                    account=social_account,
                    app=social_app,
                )
                # Update existing token
                social_token.token = access_token
                social_token.expires_at = timezone.now() + timedelta(
                    seconds=token_response_data.get("expires_in", 3600)
                )
                # Only update refresh_token if we got a new one
                if refresh_token:
                    social_token.token_secret = refresh_token
                social_token.save()
                print(f"✅ Updated existing SocialToken for {user.gmail}")
            except SocialToken.DoesNotExist:
                # Create new token
                social_token = SocialToken.objects.create(
                    account=social_account,
                    app=social_app,
                    token=access_token,
                    token_secret=refresh_token,
                    expires_at=timezone.now()
                    + timedelta(seconds=token_response_data.get("expires_in", 3600)),
                )
                print(f"✅ Created new SocialToken for {user.gmail}")

            print(f"✅ Created/updated SocialAccount and SocialToken for {user.gmail}")
            print(f"   Access token: {access_token[:20]}...")
            print(
                f"   Refresh token: {token_response_data.get('refresh_token', 'None')[:20] if token_response_data.get('refresh_token') else 'None'}..."
            )

            # Step 5: Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            # Add custom claims to JWT
            refresh["user_id"] = user.user_id  # Use the unique user_id field
            refresh["role"] = user.role
            refresh["fullname"] = user.fullname
            refresh["gmail"] = user.gmail
            
            access_token_jwt = str(refresh.access_token)

            return JsonResponse(
                {
                    "access": access_token_jwt,
                    "refresh": str(refresh),
                    "user": {
                        "id": user.id,
                        "user_id": user.user_id,  # Include the unique user_id
                        "fullname": user.fullname,
                        "gmail": user.gmail,
                        "role": user.role,
                        "is_active": user.is_active,
                        "picture": picture,
                        "created_at": user.created_at.isoformat() if user.created_at else None,
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


# ==========================================
# ONBOARDING ENDPOINTS
# ==========================================

@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboard_user(request):
    """
    Onboard a new user (Admin only).
    
    Creates a new user account with is_active=True.
    Only admins can onboard new users.
    
    Request body:
    {
        "fullname": "John Doe",
        "gmail": "john.doe@example.com",
        "role": "staff"  # Options: admin, manager, staff
    }
    """
    try:
        # Check if requesting user is an admin
        if request.user.role != "admin":
            return Response(
                {"error": "Permission denied. Only admins can onboard users."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = OnboardUserSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid data", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        gmail = serializer.validated_data["gmail"]
        
        # Check if user already exists
        if CustomUser.objects.filter(gmail=gmail).exists():
            existing_user = CustomUser.objects.get(gmail=gmail)
            if existing_user.is_active:
                return Response(
                    {"error": f"User with email {gmail} is already onboarded."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            else:
                # Activate existing inactive user
                existing_user.is_active = True
                existing_user.fullname = serializer.validated_data["fullname"]
                existing_user.role = serializer.validated_data.get("role", "staff")
                existing_user.created_by = request.user.gmail
                existing_user.save()
                
                # Ensure user has quota (restore if deactivated)
                quota_created = False
                try:
                    # First try to restore if exists
                    restore_response = requests.post(
                        f"http://localhost:8011/quota/admin/user/{existing_user.user_id}/restore",
                        timeout=5
                    )
                    if restore_response.status_code == 200:
                        quota_created = True
                        print(f"✅ Restored quota for user {existing_user.user_id}")
                    elif restore_response.status_code == 404:
                        # User doesn't exist in quota, create new
                        create_response = requests.post(
                            "http://localhost:8011/quota/admin/user/create",
                            json={
                                "user_id": existing_user.user_id,
                                "fullname": existing_user.fullname,
                                "tier": "free"
                            },
                            timeout=5
                        )
                        if create_response.status_code in [200, 201]:
                            quota_created = True
                            print(f"✅ Created quota for user {existing_user.user_id}")
                except Exception as quota_err:
                    print(f"⚠️ Quota service unavailable: {quota_err}")
                
                # Log the activation
                log_admin_activity(request, "activate", existing_user, {
                    "previous_status": "inactive",
                    "new_status": "active",
                    "role": existing_user.role,
                    "quota_restored": quota_created
                })
                
                return Response(
                    {
                        "message": f"User {gmail} has been activated.",
                        "user": UserSerializer(existing_user).data,
                        "quota_restored": quota_created
                    },
                    status=status.HTTP_200_OK
                )
        
        # Create new onboarded user
        new_user = CustomUser.objects.create(
            fullname=serializer.validated_data["fullname"],
            gmail=gmail,
            role=serializer.validated_data.get("role", "staff"),
            is_active=True,  # Onboarded users are active
            created_by=request.user.gmail,
        )
        
        # Create user quota in token-quota-service
        quota_created = False
        try:
            quota_response = requests.post(
                "http://localhost:8011/quota/admin/user/create",
                json={
                    "user_id": new_user.user_id,
                    "fullname": new_user.fullname,
                    "tier": "free"
                },
                timeout=5
            )
            if quota_response.status_code in [200, 201]:
                quota_created = True
                print(f"✅ Created quota for user {new_user.user_id}")
            else:
                print(f"⚠️ Failed to create quota: {quota_response.text}")
        except Exception as quota_err:
            print(f"⚠️ Quota service unavailable: {quota_err}")
        
        # Log the onboarding
        log_admin_activity(request, "onboard", new_user, {
            "role": new_user.role,
            "quota_created": quota_created
        })
        
        print(f"✅ Admin {request.user.gmail} onboarded new user: {gmail}")
        
        return Response(
            {
                "message": f"User {gmail} has been successfully onboarded.",
                "user": UserSerializer(new_user).data,
                "quota_created": quota_created
            },
            status=status.HTTP_201_CREATED
        )
        
    except Exception as e:
        import traceback
        print(f"Error in onboard_user: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": f"Failed to onboard user: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_users(request):
    """
    List all users (Admin only).
    
    Query params:
    - role: Filter by role (admin, manager, staff)
    - is_active: Filter by active status (true/false)
    """
    try:
        # Check if requesting user is an admin
        if request.user.role != "admin":
            return Response(
                {"error": "Permission denied. Only admins can view all users."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        users = CustomUser.objects.all().order_by("-created_at")
        
        # Filter by role if provided
        role = request.query_params.get("role")
        if role:
            users = users.filter(role=role)
        
        # Filter by is_active if provided
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            is_active_bool = is_active.lower() == "true"
            users = users.filter(is_active=is_active_bool)
        
        serializer = UserSerializer(users, many=True)
        
        return Response(
            {
                "count": users.count(),
                "users": serializer.data
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        import traceback
        print(f"Error in list_users: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": f"Failed to list users: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_user(request, user_id):
    """
    Update a user's details (Admin only).
    
    Request body (all fields optional):
    {
        "fullname": "New Name",
        "role": "manager",
        "is_active": false
    }
    """
    try:
        # Check if requesting user is an admin
        if request.user.role != "admin":
            return Response(
                {"error": "Permission denied. Only admins can update users."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": f"User with ID {user_id} not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Track changes for logging
        changes = {}
        old_values = {}
        
        # Update fields if provided
        if "fullname" in request.data and request.data["fullname"] != user.fullname:
            old_values["fullname"] = user.fullname
            user.fullname = request.data["fullname"]
            changes["fullname"] = request.data["fullname"]
        if "role" in request.data and request.data["role"] != user.role:
            old_values["role"] = user.role
            user.role = request.data["role"]
            changes["role"] = request.data["role"]
        if "is_active" in request.data and request.data["is_active"] != user.is_active:
            old_values["is_active"] = user.is_active
            user.is_active = request.data["is_active"]
            changes["is_active"] = request.data["is_active"]
            
            # Handle quota activation/deactivation based on is_active change
            if request.data["is_active"] == True and old_values["is_active"] == False:
                # User is being reactivated - restore quota
                try:
                    restore_response = requests.post(
                        f"http://localhost:8011/quota/admin/user/{user.user_id}/restore",
                        timeout=5
                    )
                    if restore_response.status_code == 200:
                        changes["quota_restored"] = True
                        print(f"✅ Restored quota for user {user.user_id}")
                    else:
                        changes["quota_restored"] = False
                        print(f"⚠️ Failed to restore quota: {restore_response.text}")
                except Exception as quota_err:
                    changes["quota_restored"] = False
                    print(f"⚠️ Quota service unavailable for restore: {quota_err}")
            elif request.data["is_active"] == False and old_values["is_active"] == True:
                # User is being deactivated - deactivate quota
                try:
                    deactivate_response = requests.post(
                        f"http://localhost:8011/quota/admin/user/{user.user_id}/deactivate",
                        timeout=5
                    )
                    if deactivate_response.status_code == 200:
                        changes["quota_deactivated"] = True
                        print(f"✅ Deactivated quota for user {user.user_id}")
                    else:
                        changes["quota_deactivated"] = False
                        print(f"⚠️ Failed to deactivate quota: {deactivate_response.text}")
                except Exception as quota_err:
                    changes["quota_deactivated"] = False
                    print(f"⚠️ Quota service unavailable for deactivate: {quota_err}")
        
        user.save()
        
        # Log the update if there were changes
        if changes:
            log_admin_activity(request, "update", user, {
                "old_values": old_values,
                "new_values": changes
            })
        
        print(f"✅ Admin {request.user.gmail} updated user: {user.gmail}")
        
        return Response(
            {
                "message": f"User {user.gmail} has been updated.",
                "user": UserSerializer(user).data
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        import traceback
        print(f"Error in update_user: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": f"Failed to update user: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def deactivate_user(request, user_id):
    """
    Deactivate a user (Admin only). Soft delete - sets is_active=False.
    Also deactivates the user's quota in the token-quota-service.
    """
    try:
        # Check if requesting user is an admin
        if request.user.role != "admin":
            return Response(
                {"error": "Permission denied. Only admins can deactivate users."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response(
                {"error": f"User with ID {user_id} not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent self-deactivation
        if user.id == request.user.id:
            return Response(
                {"error": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user.is_active = False
        user.save()
        
        # Deactivate user's quota in token-quota-service
        quota_deactivated = False
        try:
            quota_response = requests.post(
                f"http://localhost:8011/quota/admin/user/{user.user_id}/deactivate",
                timeout=5
            )
            if quota_response.status_code == 200:
                quota_deactivated = True
                print(f"✅ Deactivated quota for user {user.user_id}")
            else:
                print(f"⚠️ Failed to deactivate quota: {quota_response.text}")
        except Exception as quota_err:
            print(f"⚠️ Quota service unavailable: {quota_err}")
        
        # Log the deactivation
        log_admin_activity(request, "deactivate", user, {
            "previous_status": "active",
            "new_status": "inactive",
            "quota_deactivated": quota_deactivated
        })
        
        print(f"✅ Admin {request.user.gmail} deactivated user: {user.gmail}")
        
        return Response(
            {
                "message": f"User {user.gmail} has been deactivated.",
                "quota_deactivated": quota_deactivated
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        import traceback
        print(f"Error in deactivate_user: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": f"Failed to deactivate user: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_admin_activity_logs(request):
    """
    Get admin activity logs (Admin only).
    
    Query params:
    - action: Filter by action type (onboard, activate, deactivate, update)
    - admin_email: Filter by admin email
    - target_email: Filter by target user email
    - days: Filter logs from last N days (default: 30)
    - limit: Number of logs to return (default: 100)
    - offset: Pagination offset (default: 0)
    """
    try:
        # Check if requesting user is an admin
        if request.user.role != "admin":
            return Response(
                {"error": "Permission denied. Only admins can view activity logs."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        logs = AdminActivityLog.objects.all().order_by("-created_at")
        
        # Filter by action type
        action = request.query_params.get("action")
        if action:
            logs = logs.filter(action=action)
        
        # Filter by admin email
        admin_email = request.query_params.get("admin_email")
        if admin_email:
            logs = logs.filter(admin_email__icontains=admin_email)
        
        # Filter by target user email
        target_email = request.query_params.get("target_email")
        if target_email:
            logs = logs.filter(target_user_email__icontains=target_email)
        
        # Filter by date range
        days = request.query_params.get("days", "30")
        try:
            days = int(days)
            if days > 0:
                from_date = timezone.now() - timedelta(days=days)
                logs = logs.filter(created_at__gte=from_date)
        except ValueError:
            pass
        
        # Get total count before pagination
        total_count = logs.count()
        
        # Pagination
        limit = int(request.query_params.get("limit", "100"))
        offset = int(request.query_params.get("offset", "0"))
        logs = logs[offset:offset + limit]
        
        # Serialize the logs
        logs_data = []
        for log in logs:
            log_item = {
                "id": log.id,
                "admin_email": log.admin_email,
                "admin_name": log.admin_name,
                "action": log.action,
                "action_display": dict(AdminActivityLog.ACTION_CHOICES).get(log.action, log.action),
                "target_user_email": log.target_user_email,
                "target_user_name": log.target_user_name,
                "details": json.loads(log.details) if log.details else None,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat()
            }
            logs_data.append(log_item)
        
        return Response(
            {
                "count": total_count,
                "limit": limit,
                "offset": offset,
                "logs": logs_data
            },
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        import traceback
        print(f"Error in get_admin_activity_logs: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": f"Failed to get activity logs: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


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

        # Extract mapped columns and pairs FIRST (before any checking)
        mapped_columns = [target_col for target_col in mappings.values() if target_col]

        # Extract mapped column pairs for display
        mapped_pairs = []
        for source_col, target_col in mappings.items():
            if target_col:  # Only show actual mappings
                mapped_pairs.append(f"{source_col} → {target_col}")

        # NOW do the checking
        if not force_upload and upload_dates:
            print(f"Step 3: Checking for existing data...")

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
                        has_any_data = quick_result.get("result", {}).get(
                            "has_data", False
                        )

                        if not has_any_data:
                            # ✅ Sheet is empty, safe to proceed - SHOW MAPPED COLUMNS
                            print(
                                f"   ✅ Sheet is empty (only headers), safe to proceed"
                            )
                            return JsonResponse(
                                {
                                    "requires_confirmation": True,
                                    "confirmation_type": "safe",
                                    "conflict_data": {
                                        "total_conflicts": 0,
                                        "total_safe": len(upload_dates),
                                        "safe_dates": upload_dates[:10],
                                        "mapped_columns": mapped_columns[:10],
                                        "mapped_pairs": mapped_pairs[
                                            :10
                                        ],  # Add mapped pairs
                                    },
                                    "message": (
                                        f"📋 Upload Confirmation\n\n"
                                        f"You are uploading {len(upload_dates)} dates of data.\n"
                                        f"Date range: {upload_dates[0] if upload_dates else ''} to {upload_dates[-1] if upload_dates else ''}\n\n"
                                        f"✅ Sheet is empty - safe to upload.\n\n"
                                        f"Will map {len(mapped_pairs)} columns:\n"
                                        f"{chr(10).join(mapped_pairs[:5])}"
                                        f"{(chr(10) + '... and ' + str(len(mapped_pairs) - 5) + ' more') if len(mapped_pairs) > 5 else ''}\n\n"
                                        f"Proceed with upload?"
                                    ),
                                },
                                status=200,
                            )
                        else:
                            # ⚠️ Sheet has data - check which dates AND columns conflict
                            print(
                                f"   ⚠️ Sheet has operational data, checking conflicts..."
                            )

                            # ============================================
                            # TWO-STEP CONFLICT CHECK:
                            # Step 1: Find which rows have these dates
                            # Step 2: Check specific cells in those rows
                            # ============================================
                            print(f"   Phase 1: Finding rows by date...")
                            find_dates_response = requests.post(
                                "http://localhost:8003/execute_task",
                                json={
                                    "tool": "find_rows_by_dates",
                                    "inputs": {
                                        "sheet_id": sheet_id,
                                        "dates_to_find": upload_dates,
                                        "sheet_name": "DATA ENTRY",
                                    },
                                    "credentials_dict": user_google_credentials,
                                },
                            )

                            if find_dates_response.status_code != 200:
                                print(f"   ⚠️  Could not check dates, proceeding...")
                                # Fallback to original method if this fails
                                check_response = requests.post(
                                    "http://localhost:8003/execute_task",
                                    json={
                                        "tool": "check_dates_and_columns_have_data",
                                        "inputs": {
                                            "sheet_id": sheet_id,
                                            "dates_to_check": upload_dates,
                                            "columns_to_check": mapped_columns,
                                            "sheet_name": "DATA ENTRY",
                                        },
                                        "credentials_dict": user_google_credentials,
                                    },
                                )
                            else:
                                find_result = find_dates_response.json()

                                if find_result.get("success"):
                                    dates_found = find_result["result"]["dates_found"]
                                    dates_not_found = find_result["result"][
                                        "dates_not_found"
                                    ]
                                    date_to_row = find_result["result"]["date_to_row"]

                                    print(
                                        f"   ✓ Found {len(dates_found)} dates in sheet"
                                    )

                                    if len(dates_found) == 0:
                                        # No dates exist - safe to upload
                                        return JsonResponse(
                                            {
                                                "requires_confirmation": True,
                                                "confirmation_type": "safe",
                                                "conflict_data": {
                                                    "total_conflicts": 0,
                                                    "total_safe": len(upload_dates),
                                                    "safe_dates": upload_dates[:10],
                                                    "mapped_columns": mapped_columns[
                                                        :10
                                                    ],
                                                    "mapped_pairs": mapped_pairs[:10],
                                                },
                                                "message": (
                                                    f"📋 Upload Confirmation\n\n"
                                                    f"These dates don't exist in the sheet yet.\n"
                                                    f"Safe to upload {len(upload_dates)} new dates.\n\n"
                                                    f"Will map {len(mapped_pairs)} columns."
                                                ),
                                            },
                                            status=200,
                                        )

                                    # ============================================
                                    # STEP 2: Check specific cells in those rows
                                    # ============================================
                                    print(
                                        f"   Phase 2: Checking cells in {len(dates_found)} rows..."
                                    )

                                    # Get row numbers for found dates
                                    row_numbers = []
                                    for date in dates_found:
                                        # Normalize date to match date_to_row keys
                                        from datetime import datetime

                                        for fmt in ["%Y-%m-%d", "%d-%b-%y"]:
                                            try:
                                                parsed = datetime.strptime(
                                                    str(date), fmt
                                                )
                                                normalized = parsed.strftime("%Y-%m-%d")
                                                if normalized in date_to_row:
                                                    row_numbers.append(
                                                        date_to_row[normalized]
                                                    )
                                                break
                                            except:
                                                continue

                                    check_cells_response = requests.post(
                                        "http://localhost:8003/execute_task",
                                        json={
                                            "tool": "check_specific_cells_have_data",
                                            "inputs": {
                                                "sheet_id": sheet_id,
                                                "row_numbers": row_numbers,
                                                "column_names": mapped_columns,
                                                "sheet_name": "DATA ENTRY",
                                            },
                                            "credentials_dict": user_google_credentials,
                                        },
                                    )

                                    if check_cells_response.status_code != 200:
                                        # Fallback to original method
                                        print(
                                            f"   ⚠️  Cell check failed, using fallback..."
                                        )
                                        check_response = requests.post(
                                            "http://localhost:8003/execute_task",
                                            json={
                                                "tool": "check_dates_and_columns_have_data",
                                                "inputs": {
                                                    "sheet_id": sheet_id,
                                                    "dates_to_check": upload_dates,
                                                    "columns_to_check": mapped_columns,
                                                    "sheet_name": "DATA ENTRY",
                                                },
                                                "credentials_dict": user_google_credentials,
                                            },
                                        )
                                    else:
                                        cells_result = check_cells_response.json()

                                        if cells_result.get("success"):
                                            result_data = cells_result.get("result", {})
                                            rows_with_data = result_data.get(
                                                "rows_with_data", []
                                            )
                                            rows_without_data = result_data.get(
                                                "rows_without_data", []
                                            )

                                            if len(rows_with_data) > 0:
                                                # CONFLICTS FOUND
                                                print(
                                                    f"      ⚠️  {len(rows_with_data)} rows have data in mapped columns!"
                                                )

                                                # Build detailed conflict message
                                                conflict_details = []
                                                for row_info in rows_with_data[:3]:
                                                    cells = row_info.get(
                                                        "cells_with_data", []
                                                    )
                                                    conflict_details.append(
                                                        f"• Row {row_info['row_number']}: "
                                                        f"{len(cells)} cells have data"
                                                    )

                                                return JsonResponse(
                                                    {
                                                        "requires_confirmation": True,
                                                        "confirmation_type": "overwrite",
                                                        "conflict_data": {
                                                            "total_conflicts": len(
                                                                rows_with_data
                                                            ),
                                                            "total_safe": len(
                                                                rows_without_data
                                                            ),
                                                            "conflicting_rows": rows_with_data[
                                                                :10
                                                            ],
                                                            "mapped_columns": mapped_columns[
                                                                :10
                                                            ],
                                                            "mapped_pairs": mapped_pairs[
                                                                :10
                                                            ],
                                                        },
                                                        "message": (
                                                            f"⚠️ DATA CONFLICT WARNING\n\n"
                                                            f"{len(rows_with_data)} of {len(dates_found)} dates have data "
                                                            f"in the columns you're mapping!\n\n"
                                                            f"Conflicts:\n"
                                                            f"{chr(10).join(conflict_details)}\n\n"
                                                            f"Your upload will OVERWRITE these columns:\n"
                                                            f"{chr(10).join(mapped_pairs[:5])}\n\n"
                                                            f"⚠️ This will replace existing data.\n\n"
                                                            f"Proceed with overwrite?"
                                                        ),
                                                    },
                                                    status=200,
                                                )
                                            else:
                                                # NO CONFLICTS - Dates exist but cells are empty
                                                print(
                                                    f"      ✅ Dates exist but mapped columns are empty!"
                                                )

                                                return JsonResponse(
                                                    {
                                                        "requires_confirmation": True,
                                                        "confirmation_type": "safe",
                                                        "conflict_data": {
                                                            "total_conflicts": 0,
                                                            "total_safe": len(
                                                                dates_found
                                                            ),
                                                            "safe_dates": dates_found[
                                                                :10
                                                            ],
                                                            "mapped_columns": mapped_columns[
                                                                :10
                                                            ],
                                                            "mapped_pairs": mapped_pairs[
                                                                :10
                                                            ],
                                                        },
                                                        "message": (
                                                            f"📋 Upload Confirmation\n\n"
                                                            f"These dates exist but the columns you're mapping are empty.\n\n"
                                                            f"Will add data to:\n"
                                                            f"{chr(10).join(mapped_pairs[:5])}\n\n"
                                                            f"Proceed with upload?"
                                                        ),
                                                    },
                                                    status=200,
                                                )
                                        else:
                                            # cells_result not successful, use fallback
                                            check_response = requests.post(
                                                "http://localhost:8003/execute_task",
                                                json={
                                                    "tool": "check_dates_and_columns_have_data",
                                                    "inputs": {
                                                        "sheet_id": sheet_id,
                                                        "dates_to_check": upload_dates,
                                                        "columns_to_check": mapped_columns,
                                                        "sheet_name": "DATA ENTRY",
                                                    },
                                                    "credentials_dict": user_google_credentials,
                                                },
                                            )
                                else:
                                    # find_result not successful, use fallback
                                    check_response = requests.post(
                                        "http://localhost:8003/execute_task",
                                        json={
                                            "tool": "check_dates_and_columns_have_data",
                                            "inputs": {
                                                "sheet_id": sheet_id,
                                                "dates_to_check": upload_dates,
                                                "columns_to_check": mapped_columns,
                                                "sheet_name": "DATA ENTRY",
                                            },
                                            "credentials_dict": user_google_credentials,
                                        },
                                    )

                            # Only process check_response if it was set (fallback cases)
                            if (
                                "check_response" in locals()
                                and check_response is not None
                            ):
                                print(
                                    f"   ℹ️  Using fallback conflict detection method..."
                                )

                            if (
                                "check_response" in locals()
                                and check_response is not None
                                and check_response.status_code == 200
                            ):
                                check_result = check_response.json()
                                if check_result.get("success"):
                                    result_data = check_result.get("result", {})
                                    conflicting_cells = result_data.get(
                                        "conflicting_cells", []
                                    )
                                    dates_with_data = result_data.get(
                                        "dates_with_data", []
                                    )
                                    dates_without_data = result_data.get(
                                        "dates_without_data", []
                                    )

                                    if len(conflicting_cells) > 0:
                                        # CONFLICTS FOUND - Show details
                                        print(
                                            f"      ⚠️ {len(conflicting_cells)} dates have conflicting data!"
                                        )

                                        # Build detailed conflict message
                                        conflict_details = []
                                        for conflict in conflicting_cells[
                                            :3
                                        ]:  # Show first 3
                                            affected_cols = conflict.get(
                                                "affected_columns", []
                                            )
                                            conflict_details.append(
                                                f"• {conflict['date']} (Row {conflict['row_number']}): "
                                                f"{', '.join(affected_cols[:3])}"
                                            )

                                        return JsonResponse(
                                            {
                                                "requires_confirmation": True,
                                                "confirmation_type": "overwrite",
                                                "conflict_data": {
                                                    "total_conflicts": len(
                                                        conflicting_cells
                                                    ),
                                                    "total_safe": len(
                                                        dates_without_data
                                                    ),
                                                    "conflicting_dates": dates_with_data[
                                                        :10
                                                    ],
                                                    "safe_dates": dates_without_data[
                                                        :5
                                                    ],
                                                    "sample_conflicts": conflicting_cells[
                                                        :5
                                                    ],
                                                    "mapped_columns": mapped_columns[
                                                        :10
                                                    ],
                                                    "mapped_pairs": mapped_pairs[:10],
                                                },
                                                "message": (
                                                    f"⚠️ DATA CONFLICT WARNING\n\n"
                                                    f"{len(conflicting_cells)} of {len(upload_dates)} dates have existing data "
                                                    f"in columns you're trying to map!\n\n"
                                                    f"Conflicts found:\n"
                                                    f"{chr(10).join(conflict_details)}"
                                                    f"{(chr(10) + '... and ' + str(len(conflicting_cells) - 3) + ' more') if len(conflicting_cells) > 3 else ''}\n\n"
                                                    f"Your upload will OVERWRITE these columns:\n"
                                                    f"{chr(10).join(mapped_pairs[:3])}"
                                                    f"{(chr(10) + '... and ' + str(len(mapped_pairs) - 3) + ' more') if len(mapped_pairs) > 3 else ''}\n\n"
                                                    f"⚠️ This will replace existing operational data.\n\n"
                                                    f"Proceed with overwrite?"
                                                ),
                                            },
                                            status=200,
                                        )
                                    else:
                                        # NO CONFLICTS - Dates exist but mapped columns are empty
                                        print(
                                            f"      ✅ Dates exist but mapped columns are empty - safe!"
                                        )
                                        return JsonResponse(
                                            {
                                                "requires_confirmation": True,
                                                "confirmation_type": "safe",
                                                "conflict_data": {
                                                    "total_conflicts": 0,
                                                    "total_safe": len(upload_dates),
                                                    "safe_dates": upload_dates[:10],
                                                    "mapped_columns": mapped_columns[
                                                        :10
                                                    ],
                                                    "mapped_pairs": mapped_pairs[:10],
                                                },
                                                "message": (
                                                    f"📋 Upload Confirmation\n\n"
                                                    f"You are uploading {len(upload_dates)} dates of data.\n\n"
                                                    f"✅ These dates exist but the columns you're mapping are empty.\n\n"
                                                    f"Will add data to these columns:\n"
                                                    f"{chr(10).join(mapped_pairs[:5])}"
                                                    f"{(chr(10) + '... and ' + str(len(mapped_pairs) - 5) + ' more') if len(mapped_pairs) > 5 else ''}\n\n"
                                                    f"Proceed with upload?"
                                                ),
                                            },
                                            status=200,
                                        )
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


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def abc_analysis_workflow(request):
    """
    Monthly ABC Analysis workflow - Direct integration like mapping agent
    Analyzes transaction data by month and uploads to Google Sheets
    """
    try:
        file = request.FILES.get("file")

        if not file:
            return JsonResponse({"error": "No file uploaded"}, status=400)

        # ============================================
        # GET USER CREDENTIALS
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
        # CALL ABC ANALYSIS AGENT
        # ============================================
        print(f"📊 Processing ABC Analysis for file: {file.name}")

        # Prepare file for upload to ABC agent
        files = {"file": (file.name, file.read(), file.content_type)}
        data = {"credentials": json.dumps(user_google_credentials)}

        # Call ABC Analysis Agent
        abc_response = requests.post(
            f"{settings.ABC_AGENT_URL}/analyze",
            files=files,
            data=data,
            timeout=120,  # Allow up to 2 minutes for processing
        )

        if abc_response.status_code != 200:
            error_detail = abc_response.text
            print(f"❌ ABC Agent Error: {error_detail}")
            return JsonResponse(
                {"error": f"ABC Analysis failed: {error_detail}"}, status=500
            )

        result = abc_response.json()

        if not result.get("success"):
            return JsonResponse(
                {"error": result.get("error", "Analysis failed")}, status=500
            )

        # Extract results
        analysis_data = result.get("result", {})
        sheet_url = analysis_data.get("sheet_url")
        monthly_summary = analysis_data.get("monthly_summary", {})
        months_analyzed = analysis_data.get("months_analyzed", [])

        print(f"   ✅ Analysis complete: {len(months_analyzed)} months analyzed")
        print(f"   📊 Sheet URL: {sheet_url}")

        return JsonResponse(
            {
                "success": True,
                "sheet_url": sheet_url,
                "sheet_id": analysis_data.get("sheet_id"),
                "total_transactions": analysis_data.get("total_transactions"),
                "months_analyzed": months_analyzed,
                "monthly_summary": monthly_summary,
                "message": f"Successfully analyzed {len(months_analyzed)} months of data",
            },
            status=200,
        )

    except requests.exceptions.Timeout:
        print("❌ ABC Analysis timeout")
        return JsonResponse(
            {"error": "Analysis took too long. Please try with a smaller file."},
            status=504,
        )
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to ABC Agent")
        return JsonResponse(
            {"error": "ABC Analysis service is not available. Please contact support."},
            status=503,
        )
    except Exception as e:
        import traceback

        print(f"❌ Error in abc_analysis_workflow: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({"error": f"Analysis failed: {str(e)}"}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def workload_analysis_workflow(request):
    """
    Workload Analysis workflow - Analyzes TIME & MOTION STUDY data
    Calculates staffing requirements, productivity, and identifies bottlenecks
    """
    try:
        file = request.FILES.get("file")

        if not file:
            return JsonResponse({"error": "No file uploaded"}, status=400)

        # Validate file type
        if not file.name.endswith((".xlsx", ".xlsm")):
            return JsonResponse(
                {"error": "File must be Excel (.xlsx or .xlsm)"}, status=400
            )

        # ============================================
        # GET USER CREDENTIALS
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
        # CALL WORKLOAD ANALYSIS AGENT
        # ============================================
        print(f"📊 Processing Workload Analysis for file: {file.name}")

        # Prepare file for upload to workload agent
        files = {"file": (file.name, file.read(), file.content_type)}

        # Call Workload Analysis Agent
        workload_response = requests.post(
            f"{settings.WORKLOAD_AGENT_URL}/analyze/upload",
            files=files,
            timeout=120,  # Allow up to 2 minutes for processing
        )

        if workload_response.status_code != 200:
            error_detail = workload_response.text
            print(f"❌ Workload Agent Error: {error_detail}")

            # Try to parse error detail
            try:
                error_json = workload_response.json()
                error_message = error_json.get("detail", error_detail)
            except:
                error_message = error_detail

            return JsonResponse(
                {"error": f"Workload Analysis failed: {error_message}"}, status=500
            )

        result = workload_response.json()

        if not result.get("status") == "success":
            return JsonResponse(
                {"error": result.get("error", "Analysis failed")}, status=500
            )

        # Extract results
        summary = result.get("summary", {})
        processes = result.get("processes", [])
        bottleneck = result.get("bottleneck", {})
        ranking = result.get("ranking", [])

        print(
            f"   ✅ Analysis complete: {summary.get('total_processes')} processes analyzed"
        )
        print(f"   🎯 Bottleneck: {bottleneck.get('process_name')}")

        return JsonResponse(
            {
                "success": True,
                "filename": file.name,
                "upload_timestamp": result.get("upload_timestamp"),
                "summary": summary,
                "processes": processes,
                "bottleneck": bottleneck,
                "ranking": ranking,
                "message": f"Successfully analyzed {summary.get('total_processes')} processes",
            },
            status=200,
        )

    except requests.exceptions.Timeout:
        print("❌ Workload Analysis timeout")
        return JsonResponse(
            {"error": "Analysis took too long. Please try with a smaller file."},
            status=504,
        )
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Workload Agent")
        return JsonResponse(
            {
                "error": "Workload Analysis service is not available. Please ensure the agent is running on port 8008."
            },
            status=503,
        )
    except Exception as e:
        import traceback

        print(f"❌ Error in workload_analysis_workflow: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({"error": f"Analysis failed: {str(e)}"}, status=500)


@csrf_exempt
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_monitoring_summary(request):
    """Get monitoring summary for all agents"""
    try:
        response = requests.get("http://localhost:8009/metrics/all", timeout=5)

        if response.status_code == 200:
            return JsonResponse(response.json(), status=200)
        else:
            return JsonResponse(
                {"error": "Failed to fetch monitoring data"}, status=500
            )

    except requests.exceptions.ConnectionError:
        return JsonResponse({"error": "Monitoring service unavailable"}, status=503)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_agent_feedback(request):
    """Submit user feedback for an agent task"""
    try:
        task_id = request.data.get("task_id")
        agent_name = request.data.get("agent_name")
        rating = request.data.get("rating")
        comment = request.data.get("comment", "")

        response = requests.post(
            "http://localhost:8009/metrics/feedback",
            json={
                "task_id": task_id,
                "agent_name": agent_name,
                "rating": rating,
                "comment": comment,
                "timestamp": datetime.now().isoformat(),
            },
            timeout=5,
        )

        return JsonResponse(response.json(), status=response.status_code)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ==========================================
# DEPRECATED - MySQL functions removed
# Use the new SQLite-based endpoints:
# - POST /api/auth/google/ - Google OAuth login (requires onboarded user)
# - POST /api/users/onboard/ - Onboard new user (Admin only)
# - GET /api/users/ - List all users (Admin only)
# - PATCH /api/users/<id>/ - Update user (Admin only)
# - DELETE /api/users/<id>/deactivate/ - Deactivate user (Admin only)
# ==========================================
