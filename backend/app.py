"""HTTP API for the iPhone app (and for testing with curl).

Run: python -m backend serve      Docs at http://localhost:8000/docs
Auth: "Authorization: Bearer <token>" from `python -m backend create-user` (dev only; Sign in with
Apple replaces this with the iPhone app).
"""
from __future__ import annotations

from typing import Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .connectors import ConnectorError
from .service import Backend, describe


def create_app(backend: Optional[Backend] = None) -> FastAPI:
    be = backend or Backend(Settings.from_env())
    app = FastAPI(title="Ride data backend", version="0.1")
    app.state.backend = be

    @app.exception_handler(ConnectorError)
    async def connector_error(_req: Request, exc: ConnectorError):
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
    def rides(uid: int = Depends(user)):
        return be.rides(uid)

    @app.get("/v1/rides/{ride_id}")
    def ride(ride_id: str, samples: bool = False, uid: int = Depends(user)):
        r = be.ride(uid, ride_id)
        if r is None:
            raise HTTPException(404, "No such ride")
        out = describe(ride_id, r)
        out["totals"] = r.totals
        if samples:
            out["samples"] = [{k: v for k, v in s.__dict__.items() if v is not None} for s in r.samples]
        return out

    return app

