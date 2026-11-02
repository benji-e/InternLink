"""Single entry point and dispatch table for the employer module."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .context import AppContext
from .errors import ModuleError
from .services import (
    bulk_decide,
    change_listing_status,
    complete_placement,
    create_listing,
    decide_application,
    download_applicant_cv,
    employer_dashboard,
    get_company_status,
    get_listing_detail,
    get_thread,
    list_applicants,
    list_conversations,
    list_my_listings,
    list_my_placements,
    list_notifications,
    mark_notification_read,
    register_employer,
    send_message,
    update_company_profile,
    update_listing,
    verify_employer_email,
    view_applicant,
)
from .session import open_session

logger = logging.getLogger(__name__)


def _required(payload: Mapping, key: str):
    if key not in payload:
        raise ModuleError("invalid", f"Missing field: {key}.", {key: "Required"})
    return payload[key]


ACTIONS = {
    "get_company": lambda ctx, p: get_company_status(ctx.db, ctx.session),
    "update_company": lambda ctx, p: update_company_profile(ctx.db, ctx.session, p),
    "create_listing": lambda ctx, p: create_listing(ctx.db, ctx.session, p),
    "update_listing": lambda ctx, p: update_listing(
        ctx.db, ctx.session, _required(p, "listing_id"), p, ctx.cache
    ),
    "set_listing_status": lambda ctx, p: change_listing_status(
        ctx.db, ctx.session, _required(p, "listing_id"), _required(p, "status"), ctx.cache
    ),
    "my_listings": lambda ctx, p: list_my_listings(
        ctx.db, ctx.session, p.get("status"), p.get("search"), p.get("page", 1)
    ),
    "listing_detail": lambda ctx, p: get_listing_detail(
        ctx.db, ctx.session, _required(p, "listing_id")
    ),
    "applicants": lambda ctx, p: list_applicants(
        ctx.db,
        ctx.session,
        _required(p, "listing_id"),
        p.get("status"),
        p.get("sort", "match_score"),
        p.get("desc", True),
        p.get("page", 1),
    ),
    "view_applicant": lambda ctx, p: view_applicant(
        ctx.db, ctx.session, _required(p, "application_id")
    ),
    "download_cv": lambda ctx, p: download_applicant_cv(
        ctx.db, ctx.session, ctx.storage, _required(p, "application_id")
    ),
    "decide": lambda ctx, p: decide_application(
        ctx.db, ctx.session, _required(p, "application_id"), _required(p, "action")
    ),
    "bulk_decide": lambda ctx, p: bulk_decide(
        ctx.db, ctx.session, _required(p, "ids"), _required(p, "action")
    ),
    "send_message": lambda ctx, p: send_message(
        ctx.db, ctx.session, _required(p, "application_id"), _required(p, "body")
    ),
    "get_thread": lambda ctx, p: get_thread(
        ctx.db, ctx.session, _required(p, "application_id")
    ),
    "inbox": lambda ctx, p: list_conversations(ctx.db, ctx.session),
    "my_placements": lambda ctx, p: list_my_placements(
        ctx.db, ctx.session, p.get("status")
    ),
    "complete_placement": lambda ctx, p: complete_placement(
        ctx.db,
        ctx.session,
        _required(p, "placement_id"),
        _required(p, "completion_note"),
    ),
    "dashboard": lambda ctx, p: employer_dashboard(ctx.db, ctx.session),
    "notifications": lambda ctx, p: list_notifications(ctx.db, ctx.session),
    "mark_notification_read": lambda ctx, p: mark_notification_read(
        ctx.db, ctx.session, _required(p, "notification_id")
    ),
}

PUBLIC_ACTIONS = {
    "register": lambda ctx, p: register_employer(
        ctx.db, ctx.mailer, p, base_url=ctx.base_url
    ),
    "verify_email": lambda ctx, p: verify_employer_email(
        ctx.db, _required(p, "token")
    ),
}


def _failure(err: ModuleError) -> dict:
    return err.as_dict()


def _server_failure(action: str) -> dict:
    logger.exception("Unhandled error in employer action %r", action)
    return {
        "ok": False,
        "category": "server",
        "message": "Something went wrong.",
        "fields": {},
    }


def handle(ctx: AppContext, token: str | None, action: str, payload: Mapping | None) -> dict:
    """Authenticated entry point used by the UI, API and test scripts."""

    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        return {
            "ok": False,
            "category": "invalid",
            "message": "The request payload must be an object.",
            "fields": {},
        }
    try:
        session = open_session(ctx.db, ctx.auth, token)
        request_ctx = ctx.with_session(session)
        if action not in ACTIONS:
            raise ModuleError("invalid", "Unknown action.")
        return {"ok": True, "data": ACTIONS[action](request_ctx, payload)}
    except ModuleError as err:
        return _failure(err)
    except Exception:
        return _server_failure(action)


def handle_public(ctx: AppContext, action: str, payload: Mapping | None) -> dict:
    """Unauthenticated entry point for registration and email verification."""

    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        return {
            "ok": False,
            "category": "invalid",
            "message": "The request payload must be an object.",
            "fields": {},
        }
    try:
        if action not in PUBLIC_ACTIONS:
            raise ModuleError("invalid", "Unknown action.")
        return {"ok": True, "data": PUBLIC_ACTIONS[action](ctx, payload)}
    except ModuleError as err:
        return _failure(err)
    except Exception:
        return _server_failure(action)
