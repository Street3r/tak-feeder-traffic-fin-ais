# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Street3r
#
# Uses the dataset of Stefan Gofferje's tak-shadowfleet-id
# (https://github.com/sgofferj/tak-shadowfleet-id), CC BY-NC 4.0.
"""Shadow fleet list: daily download, last good copy on disk as fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

from .common import fetch

LOG = logging.getLogger("tak_feeder_traffic_fin_ais")

SHADOWFLEET_URL = ("https://raw.githubusercontent.com/sgofferj/tak-shadowfleet-id/"
                   "main/shadowfleet.json")


class ShadowFleet:
    """Vessels on sanctions lists, looked up by IMO or MMSI."""

    SOURCE_LINE = ("Shadow fleet list: tak-shadowfleet-id (OpenSanctions, UK FCDO), "
                   "CC BY-NC 4.0")

    def __init__(self) -> None:
        self.by_imo: dict[str, dict[str, Any]] = {}
        self.by_mmsi: dict[str, dict[str, Any]] = {}

    def load(self, entries: Any) -> int:
        """Index a list of entries; returns how many were usable."""
        by_imo: dict[str, dict[str, Any]] = {}
        by_mmsi: dict[str, dict[str, Any]] = {}
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            if entry.get("imo"):
                by_imo[str(entry["imo"])] = entry
            mmsis = entry.get("mmsi") or []
            for mmsi in mmsis if isinstance(mmsis, list) else [mmsis]:
                by_mmsi[str(mmsi)] = entry
        if by_imo or by_mmsi:
            self.by_imo, self.by_mmsi = by_imo, by_mmsi
        return len(by_imo)

    def match(self, imo: str, mmsi: str) -> Optional[dict[str, Any]]:
        """Entry for the vessel. IMO first: it stays when name, flag or MMSI change."""
        hit = self.by_imo.get(str(imo)) if imo else None
        return hit or self.by_mmsi.get(str(mmsi))

    async def refresh(self, url: str, path: str) -> bool:
        """Download the list; on failure use the copy saved last time."""
        try:
            body = await fetch(url, {"User-Agent": "tak-feeder-traffic-fin-ais"}, timeout=60)
            entries = json.loads(body)
            if self.load(entries):
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path + ".tmp", "wb") as fh:
                        fh.write(body)
                    os.replace(path + ".tmp", path)
                except OSError as exc:
                    LOG.debug("Shadow fleet list not saved: %s", exc)
                LOG.info("Shadow fleet: %d vessels", len(self.by_imo))
                return True
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
            LOG.warning("Shadow fleet download failed: %s", exc)
        if not self.by_imo:
            try:
                with open(path, encoding="utf-8") as fh:
                    count = self.load(json.load(fh))
                LOG.info("Shadow fleet: %d vessels from the saved copy", count)
            except (OSError, ValueError):
                LOG.warning("Shadow fleet: no saved copy either")
        return False

    async def keep_fresh(self, url: str, path: str) -> None:
        """Refresh daily; retry hourly after a failure."""
        while True:
            ok = await self.refresh(url, path)
            await asyncio.sleep(24 * 3600 if ok else 3600)
