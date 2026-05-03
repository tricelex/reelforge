from __future__ import annotations

from rest_framework import serializers

from ***REMOVED***.users.models import User


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["name", "url"]

        extra_kwargs = {
            "url": {"view_name": "api:user-detail", "lookup_field": "pk"},
        }


class CurrentUserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "email", "name", "is_staff", "date_joined"]
        read_only_fields = ["id", "email", "name", "is_staff", "date_joined"]
