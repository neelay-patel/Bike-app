"""HTTP API for the iPhone app (and for testing with curl).

Run: python -m backend serve      Docs at http://localhost:8000/docs
Auth: "Authorization: Bearer <token>" from `python -m backend create-user` (dev only; Sign in with
Apple replaces this with the iPhone app).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .connectors import ConnectorError
from .service import Backend, describe

log = logging.getLogger("uvicorn.error")


def create_app(backend: Optional[Backend] = None) -> FastAPI:
    be = backend or Backend(Settings.from_env(), background=True)
    app = FastAPI(title="Ride data backend", version="0.1")
    app.state.backend = be

    @app.exception_handler(ConnectorError)
    async def connector_error(req: Request, exc: ConnectorError):
        # Messages are written to be safe to show and log (never credentials).
        log.warning("%s %s -> %s", req.method, req.url.path, exc)
        return JSONResponse(status_code=400, content={"error": str(exc)})

    def user(authorization: Optional[str] = Header(None)) -> int:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing bearer token")
        uid = be.user_for_token(authorization[7:].strip())
        if uid is None:
            raise HTTPException(401, "Unknown token")
        return uid

    def sync_quietly(uid: int, provider: str, since: Optional[str]) -> None:
        try:
            be.sync(uid, provider, since)
        except ConnectorError:
            pass  # recorded on the connection; the app shows it

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/v1/connections")
    def connections(uid: int = Depends(user)):
        return be.connections(uid)

    @app.put("/v1/connections/{provider}", status_code=202)
    def connect(provider: str, tasks: BackgroundTasks, credentials: dict = Body(...),
                since: Optional[str] = None, uid: int = Depends(user)):
        """Connect a provider (e.g. garmin_personal with {"api_key": ...}) and start pulling rides."""
        be.connect(uid, provider, credentials)
        tasks.add_task(sync_quietly, uid, provider, since)
        return {"provider": provider, "state": "connected", "sync": "started"}

    @app.post("/v1/connections/{provider}/sync")
    def sync(provider: str, since: Optional[str] = None, uid: int = Depends(user)):
        return be.sync(uid, provider, since)

    @app.delete("/v1/connections/{provider}")
    def disconnect(provider: str, uid: int = Depends(user)):
        """Disconnect and delete everything this provider delivered."""
        return {"provider": provider, "recordings_deleted": be.disconnect(uid, provider)}

    @app.post("/v1/uploads/{provider}", status_code=201)
    async def upload(provider: str, request: Request, uid: int = Depends(user)):
        """Device connectors (Apple Health): the phone posts one recording JSON per workout."""
        rec = be.upload(uid, provider, await request.body())
        return {"source": rec.source, "start": rec.start, "end": rec.end, "origin": rec.origin,
                "ride_id": be.ride_id_for(uid, rec.start, rec.end)}

    @app.get("/v1/rides")
    def rides(include_hidden: bool = False, uid: int = Depends(user)):
        """Newest first. include_hidden=true adds false starts and empty recordings, marked "hidden"."""
        return be.rides(uid, include_hidden)

    @app.get("/v1/you")
    def you(uid: int = Depends(user)):
        """Tallies (all time, this year, last year, this month), streaks, personal bests, repeated
        routes and climbs, and the latest rides' notes. Rule-based text; counts visible rides only.
        "updating": true while new rides are still being worked in (results may be a little behind)."""
        return be.you(uid)

    @app.get("/v1/me")
    def me(uid: int = Depends(user)):
        row = be.db.execute("SELECT id, tz FROM users WHERE id = ?", (uid,)).fetchone()
        return {"id": row["id"], "tz": row["tz"]}

    @app.put("/v1/me")
    def update_me(body: dict = Body(...), uid: int = Depends(user)):
        """{"tz": "America/Toronto"}: the rider's time zone, for dates, years and streaks."""
        if "tz" in body:
            try:
                be.insights.set_tz(uid, str(body["tz"]))
            except Exception:
                raise HTTPException(400, f"Unknown time zone {body['tz']!r}")
        return me(uid)

    @app.patch("/v1/routes/{route_id}")
    def rename_route(route_id: str, body: dict = Body(...), uid: int = Depends(user)):
        """{"name": "Bayview loop"} names a route; {"name": null} goes back to the automatic name."""
        if not be.insights.rename(uid, "route", route_id, body.get("name")):
            raise HTTPException(404, "No such route")
        return {"id": route_id, "name": body.get("name")}

    @app.patch("/v1/climbs/{climb_id}")
    def rename_climb(climb_id: str, body: dict = Body(...), uid: int = Depends(user)):
        """{"name": "Bayview drag"} names a climb; {"name": null} goes back to the automatic name."""
        if not be.insights.rename(uid, "climb", climb_id, body.get("name")):
            raise HTTPException(404, "No such climb")
        return {"id": climb_id, "name": body.get("name")}

    @app.get("/v1/rides/{ride_id}")
    def ride(ride_id: str, samples: bool = False, uid: int = Depends(user)):
        r = be.ride(uid, ride_id)
        if r is None:
            raise HTTPException(404, "No such ride")
        out = describe(ride_id, r)
        out["totals"] = r.totals
        out["notes"] = be.notes(uid, ride_id)
        if samples:
            out["samples"] = [{k: v for k, v in s.__dict__.items() if v is not None} for s in r.samples]
        return out

    return app

