from django.shortcuts import redirect 
from django.contrib.auth.models import User
from rest_framework import generics
from .serializers import UserSerializer
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from allauth.socialaccount.models import SocialToken, SocialAccount
from django.contrib.auth.decorators import login_required
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import os

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

    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')


    social_accounts = SocialAccount.objects.filter(user=user)
    print("Social Account for user:", social_accounts)
    # try to figure out this code below.
    social_account = social_accounts.first()

    if not social_account:
        print("No social account for user:", user)
        return redirect(f'{FRONTEND_URL}/login/callback/?error=NoSocialAccount')
        #change local host if necessary
    token = SocialToken.objects.filter(account = social_account, account__provider = 'google').first()

    if token:
        print('Google token found', token.token)
        refresh = RefreshToken.for_user(user)
        # refresh_token = str(refresh) This is basically the refresh token if needed
        access_token = str(refresh.access_token)
        return redirect(f'{FRONTEND_URL}/login/callback/?access_token={access_token}')
    else:
        print('No google token found for user', user)
        return redirect(f'{FRONTEND_URL}/login/callback/?error=NoGoogleToken')

@csrf_exempt
def validate_google_token(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            google_access_token = data.get('access_token')
            print(google_access_token)

            if not google_access_token:
                return JsonResponse({'detail': 'Access token is missing.'}, status = 400)
            return JsonResponse({'valid': True})
        except json.JSONDecodeError:
            return JsonResponse({'detail': 'Invalid JSON.'}, status = 400)
    return JsonResponse({'detail': 'Method not allowed'}, status = 405)






# Create your views here.
