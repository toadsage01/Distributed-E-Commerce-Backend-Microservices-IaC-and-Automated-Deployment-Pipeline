"""Shared utilities used by every service in the platform.

Each service still owns its own DB schema and HTTP entrypoint — this package
only contains the small cross-cutting helpers (config loader, JWT helpers,
SQLAlchemy base class) that would otherwise be copy-pasted across services.
Keeping them in one place makes drift impossible.
"""
__all__ = ["config", "jwt_utils", "database"]
