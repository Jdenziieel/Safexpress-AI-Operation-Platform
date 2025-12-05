from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
import uuid


class CustomUserManager(BaseUserManager):
    """Custom user manager for CustomUser model."""
    
    def create_user(self, gmail, fullname, password=None, **extra_fields):
        """Create and save a regular user with the given email and password."""
        if not gmail:
            raise ValueError("The Gmail field must be set")
        gmail = self.normalize_email(gmail)
        # Generate user_id if not provided
        if 'user_id' not in extra_fields:
            extra_fields['user_id'] = str(uuid.uuid4())
        user = self.model(gmail=gmail, fullname=fullname, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, gmail, fullname, password=None, **extra_fields):
        """Create and save a superuser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", "admin")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(gmail, fullname, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for SafexpressOps.
    
    Fields:
        - id: Auto-generated primary key
        - fullname: User's full name
        - gmail: User's email (used as username)
        - role: User role (admin, manager, staff)
        - is_active: Whether the user account is active (onboarded)
        - created_by: Email of admin who created/onboarded this user
        - created_at: Timestamp when user was created
        - updated_at: Timestamp when user was last updated
    """
    
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("user", "User"),
    ]
    
    # Unique user identifier for external services (quota, etc.)
    user_id = models.CharField(max_length=36, unique=True, editable=False)
    
    fullname = models.CharField(max_length=255)
    gmail = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    is_active = models.BooleanField(default=False)  # False until onboarded by admin
    is_staff = models.BooleanField(default=False)   # Required for Django admin
    created_by = models.EmailField(blank=True, null=True)  # Email of admin who onboarded
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional fields for Google OAuth (optional, stored in allauth)
    google_picture = models.URLField(blank=True, null=True)
    
    objects = CustomUserManager()
    
    USERNAME_FIELD = "gmail"
    EMAIL_FIELD = "gmail"  # Tell Django/allauth that gmail is the email field
    REQUIRED_FIELDS = ["fullname"]
    
    def save(self, *args, **kwargs):
        """Override save to generate user_id if not set."""
        if not self.user_id:
            self.user_id = str(uuid.uuid4())
        super().save(*args, **kwargs)
    
    class Meta:
        db_table = "auth_user"
        verbose_name = "User"
        verbose_name_plural = "Users"
    
    def __str__(self):
        return f"{self.fullname} ({self.gmail})"
    
    @property
    def email(self):
        """Alias for gmail to maintain compatibility with Django conventions."""
        return self.gmail
    
    @email.setter
    def email(self, value):
        """Setter for email alias."""
        self.gmail = value


class AdminActivityLog(models.Model):
    """
    Model to track admin actions on user accounts.
    
    Logs actions like onboarding, deactivation, role changes, etc.
    """
    
    ACTION_CHOICES = [
        ("onboard", "Onboard User"),
        ("activate", "Activate User"),
        ("deactivate", "Deactivate User"),
        ("update_role", "Update Role"),
        ("update_name", "Update Name"),
        ("update", "Update User"),
    ]
    
    admin_email = models.EmailField(db_index=True)
    admin_name = models.CharField(max_length=255)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    target_user_email = models.EmailField()
    target_user_name = models.CharField(max_length=255)
    details = models.TextField(blank=True, null=True)  # JSON string with additional details
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = "admin_activity_log"
        verbose_name = "Admin Activity Log"
        verbose_name_plural = "Admin Activity Logs"
        ordering = ["-created_at"]
    
    def __str__(self):
        return f"{self.admin_email} - {self.action} - {self.target_user_email} ({self.created_at})"
