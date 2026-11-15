"""Thin wrapper over packaging.licenses (PEP 639 SPDX expression validation)."""
from __future__ import annotations

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression


def canonical(expr: str) -> str | None:
    try:
        return canonicalize_license_expression(expr)
    except (InvalidLicenseExpression, TypeError, ValueError):
        return None


def error(expr: str) -> str | None:
    try:
        canonicalize_license_expression(expr)
        return None
    except InvalidLicenseExpression as exc:
        return str(exc)
