from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AutomationPolicy:
    """Hard constraints that cannot be relaxed by model reasoning."""

    stamina_item_reserve: int = 2
    allow_currency_for_stamina: bool = False
    develop_current_team_only: bool = True

    def can_consume_stamina_items(self, total_owned: int, quantity: int = 1) -> bool:
        """Reserve two stamina items in total across every item type."""
        if total_owned < 0 or quantity < 1:
            return False
        return total_owned - quantity >= self.stamina_item_reserve

    def can_consume_stamina_item(self, owned: int, quantity: int = 1) -> bool:
        """Backward-compatible alias; ``owned`` means the total across all types."""
        return self.can_consume_stamina_items(owned, quantity)

    def character_is_allowed(self, character: str, current_team: set[str]) -> bool:
        if not self.develop_current_team_only:
            return True
        return bool(character) and character in current_team


DEFAULT_POLICY = AutomationPolicy()
