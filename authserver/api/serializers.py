from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from api.models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    """Serializer for CustomUser model."""
    
    class Meta:
        model = CustomUser
        fields = ("id", "user_id", "fullname", "gmail", "role", "is_active", "created_by", "google_picture", "last_login", "created_at", "updated_at")
        read_only_fields = ("id", "user_id", "last_login", "created_at", "updated_at")


class OnboardUserSerializer(serializers.ModelSerializer):
    """Serializer for onboarding new users."""
    
    class Meta:
        model = CustomUser
        fields = ("fullname", "gmail", "role")
    
    def validate_gmail(self, value):
        """Validate that the email ends with allowed domains."""
        if not value:
            raise serializers.ValidationError("Gmail is required.")
        return value.lower()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT token serializer with user role and info."""
    
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims to JWT token from CustomUser model
        token["user_id"] = user.user_id  # Use the unique user_id field
        token["role"] = user.role
        token["fullname"] = user.fullname
        token["gmail"] = user.gmail
        token["is_active"] = user.is_active
        token["picture"] = user.google_picture  # Google profile picture URL

        return token
