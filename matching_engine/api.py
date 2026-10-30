"""Recommendations API (WBS 4.6.2), built with FastAPI.

    GET /api/v1/students/me/recommendations?limit=10
    Authorization: Bearer <JWT with sub=<user_id>, role=student>

Run locally:
    set INTERNLINK_DSN=postgresql://postgres@localhost:5432/internlink
    set INTERNLINK_JWT_SECRET=<same secret the login service signs tokens with>
    uvicorn matching_engine.api:app --port 8000
Interactive docs are then at http://localhost:8000/docs
"""
import os
from contextlib import asynccontextmanager
from datetime import date

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from matching_engine.config import DEFAULT_CONFIG, ServiceConfig
from matching_engine.service import (
    MatchingUnavailable,
    ProfileIncomplete,
    recommend_for_student,
    student_id_for_user,
)


# ---- Response shapes (also shown in the /docs page) ---------------------------

class Breakdown(BaseModel):
    programme: float | None
    skills: float | None
    interests: float | None
    location: float | None  # null when the student has no preferred location


class RecommendationOut(BaseModel):
    rank: int
    listing_id: int
    title: str
    company: str
    score: int
    breakdown: Breakdown
    applied: bool
    matched_skills: list[str]
    missing_skills: list[str]
    deadline: date


class RecommendationsOut(BaseModel):
    algorithm: str
    count: int
    results: list[RecommendationOut]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


# ---- App ----------------------------------------------------------------------

def create_app(dsn: str | None = None, jwt_secret: str | None = None,
               cfg: ServiceConfig = DEFAULT_CONFIG) -> FastAPI:
    dsn = dsn or os.environ["INTERNLINK_DSN"]
    jwt_secret = jwt_secret or os.environ["INTERNLINK_JWT_SECRET"]
    pool = ConnectionPool(dsn, min_size=2, max_size=cfg.pool_size, open=False)

    @asynccontextmanager
    async def lifespan(_app):
        pool.open(wait=True)
        yield
        pool.close()

    app = FastAPI(title="InternLink matching API", version="1.0", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": exc.message}})

    def current_student_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> int:
        """SR17 / NFR05: only a logged-in student may call this endpoint."""
        if creds is None:
            raise HTTPException(401, "Not logged in", headers={"WWW-Authenticate": "Bearer"})
        try:
            claims = jwt.decode(creds.credentials, jwt_secret, algorithms=["HS256"],
                                options={"require": ["exp", "sub", "role"]})
        except jwt.PyJWTError:
            raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
        if claims["role"] != "student":
            raise HTTPException(403, "Only students can get recommendations")
        return int(claims["sub"])

    @app.get("/api/v1/students/me/recommendations", response_model=RecommendationsOut,
             summary="Ranked internship recommendations for the logged-in student (SR03)")
    def recommendations(user_id: int = Depends(current_student_user),
                        limit: int = Query(cfg.default_k, ge=1, le=cfg.max_k)):
        # NFR06: the student comes from the token, never from the URL.
        try:
            with pool.connection() as conn:
                student_id = student_id_for_user(conn, user_id)
                if student_id is None:
                    raise ProfileIncomplete("No student profile")
                result = recommend_for_student(conn, student_id, k=limit, cfg=cfg)
        except ProfileIncomplete:
            raise ApiError(422, "PROFILE_INCOMPLETE",
                           "Add your programme and at least one skill to get recommendations")
        except MatchingUnavailable:
            raise ApiError(503, "MATCHING_UNAVAILABLE", "Couldn't load recommendations. Please retry.")
        return {
            "algorithm": result.algorithm,
            "count": result.count,
            "results": [vars(r) for r in result.results],
        }

    return app


def __getattr__(name):
    # `uvicorn matching_engine.api:app` builds the app from environment variables.
    if name == "app":
        return create_app()
    raise AttributeError(name)
