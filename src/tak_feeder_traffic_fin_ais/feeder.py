# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright Stefan Gofferje (tak-feeder-traffic-fin-ais, trakbridge-plugin-ais-digitraffic)
# Copyright (C) 2026 Street3r (Python port and changes, see README)
"""Digitraffic marine AIS (MQTT) -> CoT."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import __version__
from .ais_types import category, describe
from .common import (Health, as_float, cot_event, env, env_bool, env_float, env_list,
                     remarks_text, start_mqtt)
from .shadowfleet import ShadowFleet, SHADOWFLEET_URL

LOG = logging.getLogger("tak_feeder_traffic_fin_ais")

KNOT = 0.514444  # m/s
NAV_STATUS = {
    0: "Under way using engine", 1: "At anchor", 2: "Not under command",
    3: "Restricted manoeuvrability", 4: "Constrained by draught", 5: "Moored",
    6: "Aground", 7: "Engaged in fishing", 8: "Under way sailing", 14: "AIS-SART active",
}
# Flags of convenience that trakbridge-plugin-ais-digitraffic marks suspect
# (MID -> s). Off by default; AIS_FOC_SUSPECT=1 applies them.
FOC_SUSPECT = ("351", "352", "353", "354", "355", "356", "357", "370", "371", "372",
               "373", "374", "518", "616", "620", "636", "637")
RANK = {"h": 3, "s": 2}  # an affiliation is never softened below these


@dataclass
class Settings:
    """Feeder settings from the environment (see .env.example)."""

    mqtt_url: str = "wss://meri.digitraffic.fi:443/mqtt"
    mqtt_username: str = "digitraffic"
    mqtt_password: str = "digitrafficPassword"
    digitraffic_user: str = "tak-feeder-traffic-fin-ais"
    update_interval: float = 5.0
    refresh_interval: float = 30.0
    stale_seconds: float = 90.0
    max_age: float = 600.0
    ais_types: list[int] = field(default_factory=list)
    foc_suspect: bool = False
    affil_overrides: dict[str, str] = field(default_factory=dict)
    shadowfleet: bool = False
    shadowfleet_url: str = SHADOWFLEET_URL
    data_dir: str = "/var/lib/tak-feeder"
    timezone: str = "Europe/Helsinki"
    source_line: str = "Source: Fintraffic / digitraffic.fi, CC BY 4.0"

    @classmethod
    def from_env(cls) -> "Settings":
        """Read settings (old names UPDATE_RATE still accepted)."""
        d = cls()
        overrides = {}
        for item in env_list("AIS_AFFIL_OVERRIDES"):
            mid, _, affil = item.partition(":")
            if mid.strip() and affil.strip():
                overrides[mid.strip()] = affil.strip().lower()[0]
        types = []
        for t in env_list("AIS_TYPES"):
            try:
                types.append(int(t))
            except ValueError:
                LOG.warning("AIS_TYPES: %r is not a number", t)
        return cls(
            mqtt_url=env("MQTT_URL", d.mqtt_url),
            mqtt_username=env("MQTT_USERNAME", d.mqtt_username),
            mqtt_password=env("MQTT_PASSWORD", d.mqtt_password),
            digitraffic_user=env("DIGITRAFFIC_USER", d.digitraffic_user),
            update_interval=env_float("UPDATE_INTERVAL", d.update_interval, "UPDATE_RATE"),
            refresh_interval=env_float("REFRESH_INTERVAL", d.refresh_interval),
            stale_seconds=env_float("STALE_SECONDS", d.stale_seconds),
            max_age=env_float("MAX_AGE", d.max_age),
            ais_types=types,
            foc_suspect=env_bool("AIS_FOC_SUSPECT", False),
            affil_overrides=overrides,
            shadowfleet=env_bool("SHADOWFLEET", False),
            shadowfleet_url=env("SHADOWFLEET_URL", d.shadowfleet_url),
            data_dir=env("DATA_DIR", d.data_dir),
            timezone=env("TIMEZONE", d.timezone),
            source_line=env("SOURCE_LINE", d.source_line),
        )


def load_countries(path: str = "") -> dict[str, list[str]]:
    """MID -> [affiliation, country]. AISDB (old name) can point to another file."""
    if path:
        with open(path, encoding="utf-8") as fh:
            data: dict[str, list[str]] = json.load(fh)
            return data
    text = resources.files(__package__).joinpath("countries.json").read_text("utf-8")
    loaded: dict[str, list[str]] = json.loads(text)
    return loaded


@dataclass
class Vessel:
    """What is known of one MMSI."""

    mmsi: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    sog: Optional[float] = None  # knots
    cog: Optional[float] = None
    nav_status: Optional[int] = None
    pos_time: Optional[datetime] = None
    name: str = ""
    callsign: str = ""
    imo: str = ""
    ais_type: int = 0
    destination: str = ""
    seen: float = 0.0
    sent: float = 0.0
    changed: bool = False


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


class AisSource:
    """Collects AIS messages and produces CoT."""

    def __init__(self, settings: Settings, health: Optional[Health] = None,
                 countries: Optional[dict[str, list[str]]] = None) -> None:
        self.s = settings
        self.health = health
        self.tz = ZoneInfo(settings.timezone)
        self.countries = dict(countries if countries is not None
                              else load_countries(env("AISDB", "")))
        if settings.foc_suspect:
            for mid in FOC_SUSPECT:
                if mid in self.countries:
                    self.countries[mid] = ["s", self.countries[mid][1]]
        for mid, affil in settings.affil_overrides.items():
            country = self.countries.get(mid, ["u", "unknown"])[1]
            self.countries[mid] = [affil, country]
        self.shadow = ShadowFleet()
        self.vessels: dict[str, Vessel] = {}
        self.cache: dict[str, dict[str, Any]] = {}  # metadata of earlier runs
        self.lock = threading.Lock()
        self.messages = 0
        self.client: Any = None
        self.cache_path = os.path.join(settings.data_dir, "ais-metadata.json")
        self._cache_saved = time.monotonic()

    # ------------------------------------------------------------- input
    def handle(self, topic: str, payload: bytes, now: Optional[float] = None) -> None:
        """vessels-v2/<mmsi>/location or vessels-v2/<mmsi>/metadata."""
        parts = topic.split("/")
        if len(parts) < 3:
            return
        mmsi, kind = parts[1], parts[2]
        data = json.loads(payload.decode("utf-8"))
        now = time.monotonic() if now is None else now
        with self.lock:
            self.messages += 1
            v = self.vessels.get(mmsi)
            if v is None:
                v = self.vessels[mmsi] = self._new_vessel(mmsi)
            v.seen = now
            if kind == "location":
                lat, lon = as_float(data.get("lat")), as_float(data.get("lon"))
                if lat is None or lon is None:
                    return
                v.changed = v.changed or (v.lat, v.lon) != (lat, lon)
                v.lat, v.lon = lat, lon
                sog = as_float(data.get("sog"))
                v.sog = None if sog is None or sog >= 102.3 else sog  # 102.3 = n/a
                cog = as_float(data.get("cog"))
                v.cog = None if cog is None or cog >= 360 else cog  # 360 = n/a
                nav = data.get("navStat")
                v.nav_status = nav if isinstance(nav, int) else None
                epoch = as_float(data.get("time"))
                if epoch:
                    v.pos_time = datetime.fromtimestamp(epoch, tz=timezone.utc)
            elif kind == "metadata":
                for attr, key in (("name", "name"), ("callsign", "callSign"),
                                  ("destination", "destination")):
                    if _clean(data.get(key)):
                        setattr(v, attr, _clean(data.get(key)))
                if data.get("imo"):
                    v.imo = str(data["imo"])
                if isinstance(data.get("type"), int) and data["type"]:
                    v.ais_type = data["type"]
                v.changed = True

    def _new_vessel(self, mmsi: str) -> Vessel:
        """New vessel, with its name etc. from the cache if known."""
        meta = self.cache.get(mmsi, {})
        return Vessel(mmsi, name=meta.get("name", ""), callsign=meta.get("callsign", ""),
                      imo=meta.get("imo", ""), ais_type=int(meta.get("ais_type") or 0))

    # ------------------------------------------------------------ output
    def affiliation(self, v: Vessel) -> tuple[str, str]:
        """(affiliation letter, country) from the MMSI's MID."""
        entry = self.countries.get(v.mmsi[:3])
        if not entry:
            return ("o", "unknown") if self.countries else ("u", "unknown")
        return entry[0], entry[1]

    def build(self, v: Vessel) -> bytes:
        """CoT for one vessel."""
        affil, country = self.affiliation(v)
        description, suffix = describe(v.ais_type)
        hit = self.shadow.match(v.imo, v.mmsi) if self.s.shadowfleet else None
        if hit:
            if RANK.get(affil, 1) < RANK["s"]:
                affil = "s"  # suspect, but a hostile flag stays hostile
            if not v.ais_type and hit.get("cot", "").count("-") >= 2:
                suffix = "-" + hit["cot"].split("-", 2)[2]
        cot_type = f"a-{affil}{suffix}"
        display = v.name or (f"IMO:{v.imo}" if v.imo else f"MMSI:{v.mmsi}")

        lines = [
            f"Name: {v.name}" if v.name else None,
            f"IMO: {v.imo}" if v.imo else None,
            f"MMSI: {v.mmsi}",
            f"Radio callsign: {v.callsign}" if v.callsign else None,
            f"Country (MMSI): {country}",
            f"Type: {v.ais_type} ({description})" if v.ais_type else None,
            f"Status: {NAV_STATUS[v.nav_status]}" if v.nav_status in NAV_STATUS else None,
            f"Speed: {v.sog:.1f} kn" if v.sog is not None else None,
            f"Destination: {v.destination}" if v.destination else None,
            (f"Last position: {v.pos_time.astimezone(self.tz).strftime('%H:%M:%S')}"
             if v.pos_time else None),
        ]
        tags = ["AIS", category(v.ais_type)] if v.ais_type else ["AIS"]
        source = self.s.source_line
        if hit:
            lines += [
                "SHADOW FLEET (sanctions list)",
                f"Sanctions: {', '.join(hit.get('sanctions_origin', []))}"
                if hit.get("sanctions_origin") else None,
                f"Other names: {', '.join(hit['names'])}" if hit.get("names") else None,
                f"Flag (list): {hit['flag']}" if hit.get("flag") else None,
                f"Type (list): {hit['type']}" if hit.get("type") else None,
                f"Operator: {hit['operator']}"
                if hit.get("operator") and hit["operator"] != "nan" else None,
            ]
            source += "\n" + ShadowFleet.SOURCE_LINE
            tags.append("shadowfleet")
        return cot_event(
            uid=f"AIS-{v.mmsi}",  # as in upstream
            cot_type=cot_type,
            lat=v.lat or 0.0, lon=v.lon or 0.0,
            callsign=display,
            remarks=remarks_text(lines, source, tags),
            stale=self.s.stale_seconds,
            course=v.cog or 0.0,
            speed=(v.sog or 0.0) * KNOT,
        )

    def collect(self, now: Optional[float] = None) -> list[bytes]:
        """Changed vessels, plus unchanged ones every refresh interval."""
        now = time.monotonic() if now is None else now
        events = []
        with self.lock:
            for mmsi in [m for m, v in self.vessels.items() if now - v.seen > self.s.max_age]:
                del self.vessels[mmsi]
            for v in self.vessels.values():
                if v.lat is None or v.lon is None:
                    continue
                if self.s.ais_types and v.ais_type not in self.s.ais_types:
                    continue
                if v.changed or now - v.sent >= self.s.refresh_interval:
                    events.append(self.build(v))
                    v.sent, v.changed = now, False
            messages, self.messages = self.messages, 0
        if self.health is not None:
            if messages:
                self.health.ok()
            self.health.check_silence()
        return events

    # ------------------------------------------------- metadata on disk
    def load_cache(self) -> None:
        """Names etc. from the last run, so markers have names right away."""
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                cached = json.load(fh)
        except (OSError, ValueError):
            return
        if isinstance(cached, dict):
            with self.lock:
                self.cache = cached
        LOG.info("AIS: %d vessels in the metadata cache", len(self.cache))

    def save_cache(self, keep_days: float = 30) -> None:
        """Merge known metadata into the cache file (atomic write)."""
        wall = time.time()
        with self.lock:
            for v in self.vessels.values():
                if v.name or v.imo:
                    self.cache[v.mmsi] = {"name": v.name, "callsign": v.callsign,
                                          "imo": v.imo, "ais_type": v.ais_type, "seen": wall}
            self.cache = {m: c for m, c in self.cache.items()
                          if wall - c.get("seen", wall) < keep_days * 86400}
            cached = dict(self.cache)
        try:
            os.makedirs(self.s.data_dir, exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(cached, fh)
            os.replace(tmp, self.cache_path)
        except OSError as exc:
            LOG.warning("AIS metadata cache not saved (%s): %s", self.cache_path, exc)

    # --------------------------------------------------------- protocol
    async def events(self) -> list[bytes]:
        """Source protocol: events for this round (and save the cache now and then)."""
        if time.monotonic() - self._cache_saved > 600:
            self._cache_saved = time.monotonic()
            self.save_cache()
        return self.collect()

    async def start(self) -> None:
        """Load the cache, connect to Digitraffic, keep the shadow fleet list fresh."""
        self.load_cache()
        self.client = start_mqtt(
            "Digitraffic AIS", self.s.mqtt_url, ["vessels-v2/#"], self.handle,
            client_id=f"{self.s.digitraffic_user}-{__version__}-{uuid.uuid4().hex[:8]}",
            username=self.s.mqtt_username, password=self.s.mqtt_password,
        )
        if self.s.shadowfleet:
            await self.shadow.keep_fresh(self.s.shadowfleet_url,
                                         os.path.join(self.s.data_dir, "shadowfleet.json"))
