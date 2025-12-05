from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    """Admin configuration for CustomUser model."""
    
    model = CustomUser
    list_display = ("gmail", "fullname", "role", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_staff", "created_at")
    search_fields = ("gmail", "fullname")
    ordering = ("-created_at",)
    
    fieldsets = (
        (None, {"fields": ("gmail", "password")}),
        ("Personal Info", {"fields": ("fullname", "google_picture")}),
        ("Permissions", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Onboarding", {"fields": ("created_by",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    
    readonly_fields = ("created_at", "updated_at")
    
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("gmail", "fullname", "role", "password1", "password2", "is_active", "is_staff"),
        }),
    )


admin.site.register(CustomUser, CustomUserAdmin)
