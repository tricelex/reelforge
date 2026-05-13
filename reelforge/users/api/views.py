from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import RetrieveAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from reelforge.users.api.serializers import CurrentUserSerializer
from reelforge.users.api.serializers import UserSerializer
from reelforge.users.models import User

if TYPE_CHECKING:
    from rest_framework.request import Request


class UserViewSet(RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "pk"

    def get_queryset(self, *_args: Any, **_kwargs: Any) -> Any:
        assert isinstance(self.request.user.id, int)
        return self.queryset.filter(id=self.request.user.id)

    @action(detail=False)
    def me(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(status=status.HTTP_200_OK, data=serializer.data)


@extend_schema(tags=["auth"], summary="Get the currently authenticated user")
class CurrentUserView(RetrieveAPIView):
    serializer_class = CurrentUserSerializer

    def get_object(self) -> User:
        return self.request.user  # type: ignore[return-value]
