from rest_framework.response import Response
from rest_framework import status

class ReadOnlyMixin:
    def destroy(self, request, pk, format=None):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def create(self, request, *args, **kwargs):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def patch(self, request, *args, **kwargs):
        """
        This endpoint is readonly.
        """
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)