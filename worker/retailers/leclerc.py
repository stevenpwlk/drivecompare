from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BasketRecap:
    total: float
    loyalty_gain: float
    items: list[dict]


def login(page):
    # TODO: implement login URL and selectors for Leclerc
    raise NotImplementedError("TODO: implement login for Leclerc")


def search(page, query: str) -> list[dict]:
    # TODO: implement search URL and selectors for Leclerc
    return [{"name": query, "price": 1.99, "sku": "LECLERC-MOCK"}]


def clear_basket(page):
    # TODO: implement basket clearing for Leclerc
    return True


def fill_basket(page, items: list[dict]):
    # TODO: implement basket filling for Leclerc
    return True


def read_recap(page) -> BasketRecap:
    # TODO: implement recap reading for Leclerc
    return BasketRecap(total=0.0, loyalty_gain=0.0, items=[])
