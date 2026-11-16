"""HTTP API for the iPhone app (and for testing with curl).

Run: python -m backend serve      Docs at http://localhost:8000/docs
Auth: "Authorization: Bearer <token>" from `python -m backend create-user` (dev only; Sign in with
Apple replaces this with the iPhone app).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

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

    @app.post("/v1/metrics/{provider}", status_code=201)
    async def upload_metrics(provider: str, request: Request, uid: int = Depends(user)):
        """Recovery and fitness readings (VO2 max, HRV, resting heart rate, Cardio Recovery), in
        batches: {"format": "rideengine.metrics/1", "metrics": [...]}. Repeats are ignored."""
        return be.upload_metrics(uid, provider, await request.body())

    @app.get("/v1/recovery")
    def recovery(uid: int = Depends(user)):
        """How recovered the rider looks (HRV and resting heart rate against their usual range),
        VO2 max, and heart-rate recovery after rides. Rule-based; for the rider only."""
        return be.recovery(uid)

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
        """The rider: time zone, name (for the rider card) and avatar spec (null until they make one)."""
        return be.me(uid)

    @app.put("/v1/me")
    def update_me(body: dict = Body(...), uid: int = Depends(user)):
        """Any of {"tz": "America/Toronto", "name": "Neelay", "avatar": {...}}. An avatar of null
        removes it (cards go back to having none)."""
        try:
            return be.update_me(uid, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            if "tz" in body:
                raise HTTPException(400, f"Unknown time zone {body['tz']!r}") from exc
            raise

    @app.get("/v1/avatar/options")
    def avatar_options():
        """Every avatar part and its choices, with colours for the swatches (no login needed)."""
        from rideengine.card import avatar as av
        return {"options": av.OPTIONS, "default": av.DEFAULT,
                "colors": {"skin": av.SKIN, "hair_color": av.HAIR_COLOR, "kit": av.KIT, "frame": av.FRAME,
                           "tyres": av.TYRES}}

    @app.post("/v1/avatar/preview")
    def avatar_preview(spec: dict = Body(...), uid: int = Depends(user)):
        """The avatar drawn from a spec, as SVG, for the builder's live preview (nothing is saved)."""
        from rideengine.card.avatar import avatar_svg
        return Response(avatar_svg(spec, size=240), media_type="image/svg+xml")

    @app.get("/v1/goals/options")
    def goal_options(uid: int = Depends(user)):
        """The four objectives and what each can look like, quoting the rider's own bests; their seasons."""
        return be.goal_options(uid)

    @app.post("/v1/goals/preview")
    def goal_preview(goal: dict = Body(...), uid: int = Depends(user)):
        """What a goal would mean (the reveal) and what we'd watch (markers), without saving it."""
        try:
            return be.goal_view(uid, be.check_goal(uid, goal))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.put("/v1/goals/current")
    def set_goal(goal: dict = Body(...), uid: int = Depends(user)):
        """Set the rider's goal ({"objective", "aspiration", "words", "tags", "params", "ready_by"}). The previous
        one is kept as history."""
        try:
            return be.set_goal(uid, goal)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/v1/goals/current")
    def current_goal(uid: int = Depends(user)):
        """The active goal with its reveal and markers worked out from today's data, or 404 if none."""
        g = be.current_goal(uid)
        if g is None:
            raise HTTPException(404, "No goal set")
        return g

    @app.delete("/v1/goals/current")
    def end_goal(uid: int = Depends(user)):
        return {"ended": be.end_goal(uid)}

    @app.get("/v1/plan")
    def plan(uid: int = Depends(user)):
        """The training plan for the active goal: weeks of structured sessions with targets (watts when FTP
        is known, heart rate always) and each session's status (done, missed, today, upcoming)."""
        v = be.plan_view(uid)
        if v is None:
            raise HTTPException(404, "No plan: set a goal first")
        return v

    @app.put("/v1/plan/settings")
    def plan_settings(body: dict = Body(...), uid: int = Depends(user)):
        """{"days": ["Mon", ...], "times": {"Mon": "07:00"}, "weekly_hours": 4.5}: rebuilds from today on."""
        try:
            if be.make_plan(uid, body.get("days"), body.get("times"), body.get("weekly_hours")) is None:
                raise HTTPException(404, "No plan: set a goal first")
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        return be.plan_view(uid)

    @app.get("/v1/plan/sessions/{session_id}")
    def plan_session(session_id: str, uid: int = Depends(user)):
        s = be.plan_session(uid, session_id)
        if s is None:
            raise HTTPException(404, "No such session")
        return s

    @app.put("/v1/plan/sessions/{session_id}/done")
    def session_done(session_id: str, uid: int = Depends(user)):
        if not be.mark_done(uid, session_id, True):
            raise HTTPException(404, "No such session")
        return {"id": session_id, "done": True}

    @app.delete("/v1/plan/sessions/{session_id}/done")
    def session_undone(session_id: str, uid: int = Depends(user)):
        if not be.mark_done(uid, session_id, False):
            raise HTTPException(404, "No such session")
        return {"id": session_id, "done": False}

    @app.get("/v1/plan/sessions/{session_id}/zwift")
    def session_zwo(session_id: str, uid: int = Depends(user)):
        """The session as a Zwift workout (.zwo): put it in Documents/Zwift/Workouts and Zwift sets the
        KICKR's resistance for each step."""
        zwo = be.session_zwo(uid, session_id)
        if zwo is None:
            raise HTTPException(404, "No such structured session")
        return Response(zwo, media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{session_id}.zwo"'})

    @app.get("/v1/plan/calendar")
    def plan_calendar(request: Request, reset: bool = False, uid: int = Depends(user)):
        """The address of the rider's training calendar feed, to subscribe to from any calendar app."""
        token = be.calendar_token(uid, reset=reset)
        url = str(request.base_url).rstrip("/") + f"/calendar/{token}.ics"
        return {"url": url, "webcal": "webcal://" + url.split("://", 1)[1]}

    @app.get("/calendar/{token}.ics")
    def calendar_feed(token: str):
        """The training plan as a calendar feed. No login: the address itself is the secret."""
        ics = be.calendar_ics(token)
        if ics is None:
            raise HTTPException(404, "Unknown calendar")
        return Response(ics, media_type="text/calendar; charset=utf-8")

    @app.get("/v1/collection")
    def collection(uid: int = Depends(user)):
        """The fun bucket: badges (earned or how close), the rider card's ratings out of 99, and the
        season binder (every ride's card per year, holo for personal bests, gaps for missed weeks)."""
        return be.collection(uid)

    @app.get("/v1/rider/card", response_class=HTMLResponse)
    def rider_card(fonts: str = "google", background: str = "#FFFFFF", uid: int = Depends(user)):
        """The rider card (avatar, ratings, type) as one HTML page, like the ride cards."""
        if fonts not in ("google", "local") or not re.fullmatch(r"#[0-9A-Fa-f]{6}|transparent", background):
            raise HTTPException(400, "fonts must be google or local; background a #RRGGBB colour or transparent")
        return HTMLResponse(be.rider_card_html(uid, fonts=fonts, background=background))

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

    @app.delete("/v1/rides/{ride_id}")
    def delete_ride(ride_id: str, uid: int = Depends(user)):
        """Delete a ride and every recording merged into it. It stays deleted: a later sync or upload of
        the same activity is ignored."""
        n = be.delete_ride(uid, ride_id)
        if n is None:
            raise HTTPException(404, "No such ride")
        return {"ride_id": ride_id, "recordings_deleted": n}

    @app.get("/v1/rides/{ride_id}/card", response_class=HTMLResponse)
    def card(ride_id: str, fonts: str = "google", background: str = "#FFFFFF", uid: int = Depends(user)):
        """The ride's collectible card as one HTML page (360x640). fonts=local: the app supplies the
        font files. The route is cut around home. Whether the ride may be shared is in the ride's
        "use" (sources' terms); the app asks before sharing when it isn't cleared."""
        if fonts not in ("google", "local") or not re.fullmatch(r"#[0-9A-Fa-f]{6}|transparent", background):
            raise HTTPException(400, "fonts must be google or local; background a #RRGGBB colour or transparent")
        html = be.card_html(uid, ride_id, fonts=fonts, background=background)
        if html is None:
            raise HTTPException(404, "No such ride")
        return HTMLResponse(html)

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

