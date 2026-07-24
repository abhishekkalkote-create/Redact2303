"""ULID-based IDs with type prefixes, e.g. org_01J..., usr_01J... (see specs/03-data-model.md)."""

from ulid import ULID


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"
