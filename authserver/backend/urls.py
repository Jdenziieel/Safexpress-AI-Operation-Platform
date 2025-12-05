from django.contrib import admin
from django.urls import path, include
from api.views import *
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf.urls.static import static
from api.views import dynamic_mapping_workflow, onboard_user, list_users, update_user, deactivate_user, get_admin_activity_logs
from api.serializers import CustomTokenObtainPairSerializer

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/user/register/", UserCreate.as_view(), name="user_create"),
    # ✅ JWT Token endpoints - Use custom serializer for role-based tokens
    path(
        "api/token/",
        TokenObtainPairView.as_view(serializer_class=CustomTokenObtainPairSerializer),
        name="token_obtain_pair",
    ),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api-auth/", include("rest_framework.urls")),
    path("accounts/", include("allauth.urls")),
    path("callback/", google_login_callback, name="callback"),
    path("api/auth/user/", UserDetailView.as_view(), name="user_detail"),
    path("api/google/validate_token/", validate_google_token, name="validate_token"),
    # ✅ Google OAuth authentication with onboarding check
    path(
        "api/auth/google/", google_auth_dynamodb, name="google_auth"
    ),
    # ✅ User Onboarding endpoints (Admin only)
    path("api/users/onboard/", onboard_user, name="onboard_user"),
    path("api/users/", list_users, name="list_users"),
    path("api/users/<int:user_id>/", update_user, name="update_user"),
    path("api/users/<int:user_id>/deactivate/", deactivate_user, name="deactivate_user"),
    # ✅ Admin Activity Logs (Admin only)
    path("api/admin/activity-logs/", get_admin_activity_logs, name="admin_activity_logs"),
    # Workflow endpoints
    path(
        "api/dynamic-mapping/upload/",
        dynamic_mapping_workflow,
        name="dynamic_mapping_workflow",
    ),
    path("api/abc-analysis/", abc_analysis_workflow, name="abc_analysis_workflow"),
    path(
        "api/workload-analysis/",
        workload_analysis_workflow,
        name="workload_analysis_workflow",
    ),
    # Monitoring endpoints
    path("api/monitoring/summary/", agent_monitoring_summary, name="agent_monitoring"),
    path("api/monitoring/feedback/", submit_agent_feedback, name="agent_feedback"),
]
