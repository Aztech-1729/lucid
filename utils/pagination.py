"""
Generic pagination utility.

All list screens use this — no list screen implements its own slicing logic.
"""

from __future__ import annotations

import math
from typing import Generic, TypeVar

T = TypeVar("T")


class Paginator(Generic[T]):
    """
    Page-based paginator for any list of items.

    Default page size is 20 items (non-configurable per spec).
    """

    def __init__(
        self,
        items: list[T],
        page: int = 1,
        page_size: int = 10,
    ) -> None:
        self._items = items
        self._page_size = min(page_size, 20)  # Hard cap at 20
        self._total_pages = max(1, math.ceil(len(items) / self._page_size))
        self._page = max(1, min(page, self._total_pages))

    @property
    def page(self) -> int:
        """Current page number (1-indexed)."""
        return self._page

    @property
    def page_size(self) -> int:
        """Items per page."""
        return self._page_size

    @property
    def total_items(self) -> int:
        """Total number of items across all pages."""
        return len(self._items)

    @property
    def total_pages(self) -> int:
        """Total number of pages."""
        return self._total_pages

    @property
    def current_page(self) -> list[T]:
        """Items for the current page."""
        start = (self._page - 1) * self._page_size
        end = start + self._page_size
        return self._items[start:end]

    @property
    def has_prev(self) -> bool:
        """Whether there is a previous page."""
        return self._page > 1

    @property
    def has_next(self) -> bool:
        """Whether there is a next page."""
        return self._page < self._total_pages

    def page_info(self) -> str:
        """Human-readable page info string."""
        return f"Page {self._page} of {self._total_pages}"

    def to_dict(self) -> dict:
        """Serialize pagination metadata (for cache storage)."""
        return {
            "page": self._page,
            "current_page": self._page,
            "page_size": self._page_size,
            "total_items": self.total_items,
            "total_pages": self._total_pages,
            "has_prev": self.has_prev,
            "has_next": self.has_next,
        }
