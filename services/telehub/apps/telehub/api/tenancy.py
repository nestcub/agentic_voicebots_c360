"""Auth + per-request organization resolution (Phase 0 plan sections 3.4 / 3.5).

Scoping is explicit: viewsets filter by `request.organization`, there is no
thread-local "current org" and no self-filtering manager.
"""

from django.conf import settings
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.permissions import BasePermission

from ..models import Organization

ORG_HEADER = "HTTP_X_ORGANIZATION"


class OrganizationRequired(APIException):
    status_code = 400
    default_detail = "This user belongs to several organizations; send an X-Organization header."
    default_code = "organization_required"


def auth_required():
    return getattr(settings, "TELEHUB_AUTH_REQUIRED", False)


def _is_authenticated(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated)


def resolve_organization(request):
    """Return the Organization this request acts in, or raise a DRF API exception."""
    slug = (request.META.get(ORG_HEADER) or "").strip()

    if not _is_authenticated(request):
        # Only reachable while TELEHUB_AUTH_REQUIRED is off (the permission rejects otherwise).
        slug = slug or settings.TELEHUB_DEFAULT_ORG_SLUG
        org = Organization.objects.filter(slug=slug, is_active=True).first()
        if org is None:
            raise NotFound("Organization not found.")
        return org

    user = request.user
    if slug:
        org = Organization.objects.filter(slug=slug, is_active=True).first()
        if user.is_staff or user.is_superuser:
            if org is None:
                raise NotFound("Organization not found.")
            return org
        if org is None or not user.memberships.filter(organization=org).exists():
            raise PermissionDenied("You are not a member of this organization.")
        return org

    orgs = list(
        Organization.objects.filter(memberships__user=user, is_active=True).distinct()[:2]
    )
    if len(orgs) == 1:
        return orgs[0]
    raise OrganizationRequired()


class IsAuthenticatedWhenRequired(BasePermission):
    """DRF default: a logged-in user, unless TELEHUB_AUTH_REQUIRED is off (the pre-login rollout)."""

    def has_permission(self, request, view):
        return (not auth_required()) or _is_authenticated(request)


class HasOrgAccess(IsAuthenticatedWhenRequired):
    """Authenticates, then resolves and attaches `request.organization`."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        request.organization = resolve_organization(request)
        return True


class OrgScopedViewSetMixin:
    """Filters every queryset to the request's org and stamps it on create.

    Objects in another org are simply absent from the queryset, so they 404
    rather than revealing that they exist.
    """

    permission_classes = [HasOrgAccess]
    org_lookup = "organization"

    def get_queryset(self):
        return super().get_queryset().filter(**{self.org_lookup: self.request.organization})

    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)
