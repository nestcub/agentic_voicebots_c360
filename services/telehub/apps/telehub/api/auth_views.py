from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Organization


class MeView(APIView):
    """The logged-in user and the orgs they can act in (feeds the dashboard's org switcher)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        is_platform_staff = user.is_staff or user.is_superuser
        if is_platform_staff:
            orgs = [
                {"slug": o.slug, "name": o.name, "role": "admin"}
                for o in Organization.objects.filter(is_active=True).order_by("name")
            ]
        else:
            orgs = [
                {"slug": m.organization.slug, "name": m.organization.name, "role": m.role}
                for m in user.memberships.select_related("organization")
                .filter(organization__is_active=True)
                .order_by("organization__name")
            ]
        return Response(
            {
                "id": user.pk,
                "username": user.get_username(),
                "is_platform_staff": is_platform_staff,
                "organizations": orgs,
            }
        )
