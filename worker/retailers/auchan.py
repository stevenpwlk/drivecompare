from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BasketRecap:
    total: float
    loyalty_gain: float
    items: list[dict]


def login(page):
    # TODO: implement login URL and selectors for Auchan
    raise NotImplementedError("TODO: implement login for Auchan")


def search(page, query: str) -> list[dict]:
    # TODO: implement search URL and selectors for Auchan
    return [{"name": query, "price": 2.05, "sku": "AUCHAN-MOCK"}]


def clear_basket(page):
    # TODO: implement basket clearing for Auchan
    return True


def fill_basket(page, items: list[dict]):
    # TODO: implement basket filling for Auchan
    return True


def read_recap(page) -> BasketRecap:
    # TODO: implement recap reading for Auchan
    return BasketRecap(total=0.0, loyalty_gain=0.0, items=[])
