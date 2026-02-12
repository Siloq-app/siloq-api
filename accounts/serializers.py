"""
Serializers for user authentication.
"""
from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    
    class Meta:
        model = User
        fields = ('id', 'email', 'username', 'first_name', 'last_name', 'created_at')
        read_only_fields = ('id', 'created_at')


class LoginSerializer(serializers.Serializer):
    """Serializer for login requests."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            # Try to authenticate using email
            user = authenticate(username=email, password=password)
            if not user:
                raise serializers.ValidationError('Invalid email or password.')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Must include "email" and "password".')

        return attrs


class RegisterSerializer(serializers.Serializer):
    """Serializer for user registration."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'}, min_length=8)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def create(self, validated_data):
        name = validated_data.pop('name', '').strip()
        first_name = validated_data.get('first_name', '').strip() or (name.split(None, 1)[0] if name else '')
        last_name = validated_data.get('last_name', '').strip() or (name.split(None, 1)[1] if len(name.split(None, 1)) > 1 else '')
        validated_data.setdefault('first_name', first_name)
        validated_data.setdefault('last_name', last_name)
        email = validated_data['email']
        password = validated_data.pop('password')
        # Use email as username for compatibility with USERNAME_FIELD = 'email'
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            subscription_status='free',  # Required NOT NULL field in database
        )
        return user
