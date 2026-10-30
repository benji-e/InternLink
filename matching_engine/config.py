"""Recommendation service settings.

The matching weights, minimum score and ranking rules live in one place only:
the database function fn_recommendations (PR #2, 03_views_functions.sql).
These settings cover what the Python service adds around it.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceConfig:
    default_k: int = 10  # SR03: top 10
    max_k: int = 50
    timeout_seconds: float = 4.0  # stop before the 5 s limit (NFR01, NFR07)
    # Database connections shared by all requests. fn_recommendations is CPU-bound, so
    # about 2x the database server's CPU cores works best (measured on 4 cores: 8).
    pool_size: int = 8
    algorithm: str = "fn_recommendations v1"


DEFAULT_CONFIG = ServiceConfig()
