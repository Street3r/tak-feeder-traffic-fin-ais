# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright Stefan Gofferje (tak-feeder-traffic-fin-ais)
# Copyright (C) 2026 Street3r (Python port, see README)
"""Run the feeder: python -m tak_feeder_traffic_fin_ais"""

from __future__ import annotations

import asyncio
import logging

from . import __version__
from .common import Health, TakSettings, env_float, run_feeder, setup_logging
from .feeder import AisSource, Settings

LOG = logging.getLogger("tak_feeder_traffic_fin_ais")


async def main() -> None:
    """Read settings and run."""
    tak = TakSettings.from_env()
    setup_logging(tak.debug)
    settings = Settings.from_env()
    LOG.info("tak-feeder-traffic-fin-ais %s -> %s (shadow fleet %s, FOC suspect %s)",
             __version__, tak.cot_url, "on" if settings.shadowfleet else "off",
             "on" if settings.foc_suspect else "off")
    health = Health(max_silence=env_float("HEALTH_MAX_SILENCE", 300.0))
    source = AisSource(settings, health)
    try:
        await run_feeder(tak, source, settings.update_interval)
    finally:
        source.save_cache()


def run() -> None:
    """Console script entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
