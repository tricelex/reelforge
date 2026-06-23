"""Application services layer.

Services coordinate multiple apps/domains to fulfil a single use case.
They live outside any single app so they can import from multiple
``server.apps.*`` packages without creating circular dependencies.

Layering rule: services may import from apps but apps must NOT import
from services.  Enforced by import-linter contract
``apps-cannot-import-services``.
"""
