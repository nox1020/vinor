from __future__ import annotations

from app.conversation.interfaces import (
    ROLE_GUEST,
    ROLE_PARTNER,
    ROLE_PREMIUM,
    ROLE_USER,
    IdentityInfo,
    RoleResolver,
)

_ORDER = (ROLE_GUEST, ROLE_USER, ROLE_PARTNER, ROLE_PREMIUM)


class RuleRoleResolver(RoleResolver):
    """Upgradeable roles — no role-picker UI."""

    def resolve(self, identity: IdentityInfo) -> str:
        role = (identity.role or ROLE_GUEST).strip() or ROLE_GUEST
        if role not in _ORDER:
            return ROLE_GUEST
        return role

    @staticmethod
    def can_upgrade(current: str, target: str) -> bool:
        try:
            return _ORDER.index(target) > _ORDER.index(current)
        except ValueError:
            return False
