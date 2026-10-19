# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the AIS feeder."""

import asyncio
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from tak_feeder_traffic_fin_ais import feeder, shadowfleet
from tak_feeder_traffic_fin_ais.ais_types import category, describe

LOC = {"time": 1760356800, "sog": 10.0, "cog": 90.0, "navStat": 0, "lat": 60.1, "lon": 24.9}
SHADOW = [{"imo": "9562233", "mmsi": ["620233000"], "names": ["Jal Vahini", "Petrel 8"],
           "type": "Bulk Carrier", "operator": "nan", "flag": "Comoros",
           "cot": "a-s-S-X-M-P", "sanctions_origin": ["UK", "OpenSanctions"]}]


def meta(**kw):
    base = {"name": "  BALTIC   STAR ", "callSign": "OJAB", "imo": 1234567, "type": 70,
            "destination": "HELSINKI"}
    base.update(kw)
    return json.dumps(base).encode()


class AisTest(unittest.TestCase):
    def make(self, **settings):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp))
        return feeder.AisSource(feeder.Settings(data_dir=tmp, **settings))

    def event(self, src, mmsi="230123456", now=0, **meta_kw):
        src.handle(f"vessels-v2/{mmsi}/metadata", meta(**meta_kw), now=now)
        src.handle(f"vessels-v2/{mmsi}/location", json.dumps(LOC).encode(), now=now)
        events = src.collect(now)
        return ET.fromstring(events[-1]) if events else None

    def test_types_from_plugin(self) -> None:
        self.assertEqual(describe(51)[1], "-S-N")  # SAR, was law enforcement
        self.assertEqual(describe(54)[1], "-S-X")  # anti-pollution, was law enforcement
        self.assertEqual(describe(30)[1], "-S-X-F")  # fishing, was missing
        self.assertEqual(category(72), "cargo")

    def test_event(self) -> None:
        ev = self.event(self.make())
        self.assertEqual(ev.get("uid"), "AIS-230123456")
        self.assertEqual(ev.get("type"), "a-f-S-X-M-C")  # Finland, cargo
        self.assertEqual(ev.find("detail/contact").get("callsign"), "BALTIC STAR")
        self.assertEqual(ev.find("detail/track").get("speed"), "5.14")
        text = ev.find("detail/remarks").text
        self.assertIn("Type: 70 (Cargo, all ships of this type)", text)
        self.assertIn("Status: Under way using engine", text)
        self.assertIn("Source: Fintraffic / digitraffic.fi, CC BY 4.0", text)
        self.assertTrue(text.endswith("#AIS #cargo"))

    def test_name_fallbacks(self) -> None:
        src = self.make()
        src.handle("vessels-v2/230000001/location", json.dumps(LOC).encode(), now=0)
        ev = ET.fromstring(src.collect(0)[0])
        self.assertEqual(ev.find("detail/contact").get("callsign"), "MMSI:230000001")

    def test_foc_and_overrides(self) -> None:
        self.assertEqual(self.event(self.make(), mmsi="636000001").get("type")[:3], "a-u")
        src = self.make(foc_suspect=True, affil_overrides={"538": "s"})
        self.assertEqual(self.event(src, mmsi="636000001").get("type")[:3], "a-s")
        self.assertEqual(self.event(src, mmsi="538000001").get("type")[:3], "a-s")
        self.assertEqual(self.event(src, mmsi="230000001").get("type")[:3], "a-f")

    def test_shadowfleet_never_softens(self) -> None:
        src = self.make(shadowfleet=True)
        src.shadow.load(SHADOW)
        ev = self.event(src, mmsi="620233000", imo=9562233)
        self.assertEqual(ev.get("type"), "a-s-S-X-M-C")
        text = ev.find("detail/remarks").text
        self.assertIn("Sanctions: UK, OpenSanctions", text)
        self.assertIn("CC BY-NC 4.0", text)
        self.assertNotIn("Operator", text)  # "nan" left out
        self.assertTrue(text.endswith("#shadowfleet"))
        # Russian flag stays hostile; matched by MMSI when the IMO is missing
        src.shadow.load([dict(SHADOW[0], imo="1", mmsi=["273000001"])])
        ev = self.event(src, mmsi="273000001", imo=0)
        self.assertEqual(ev.get("type")[:3], "a-h")
        self.assertIn("#shadowfleet", ev.find("detail/remarks").text)

    def test_shadowfleet_off_by_default(self) -> None:
        src = self.make()
        src.shadow.load(SHADOW)
        self.assertNotIn("shadowfleet", self.event(src, mmsi="620233000", imo=9562233)
                         .find("detail/remarks").text)

    def test_type_filter_and_send_rate(self) -> None:
        src = self.make(ais_types=[60])
        self.assertIsNone(self.event(src))
        src = self.make()
        self.event(src)  # 10 kn: moving, every 5 s
        self.assertEqual(src.collect(1), [])
        self.assertEqual(len(src.collect(5)), 1)  # same position re-sent
        moored = dict(LOC, sog=0.1, navStat=5)
        src.handle("vessels-v2/230123456/location", json.dumps(moored).encode(), now=6)
        self.assertEqual(len(src.collect(6)), 1)  # stopped: sent at once
        self.assertEqual(src.collect(30), [])
        self.assertEqual(len(src.collect(66)), 1)  # stopped: every 60 s
        self.assertEqual(src.collect(700), [])  # silent too long: dropped

    def test_not_available_values(self) -> None:
        src = self.make()
        src.handle("vessels-v2/230000002/location",
                   json.dumps(dict(LOC, sog=102.3, cog=360)).encode(), now=0)
        track = ET.fromstring(src.collect(0)[0]).find("detail/track")
        self.assertEqual((track.get("speed"), track.get("course")), ("0.00", "0.0"))

    def test_metadata_cache_survives_restart(self) -> None:
        src = self.make()
        self.event(src)
        src.save_cache()
        again = feeder.AisSource(src.s)
        again.load_cache()
        again.handle("vessels-v2/230123456/location", json.dumps(LOC).encode(), now=0)
        ev = ET.fromstring(again.collect(0)[0])
        self.assertEqual(ev.find("detail/contact").get("callsign"), "BALTIC STAR")

    def test_shadowfleet_download_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf.json")
            sf = shadowfleet.ShadowFleet()
            with mock.patch.object(shadowfleet, "fetch",
                                   mock.AsyncMock(return_value=json.dumps(SHADOW).encode())):
                self.assertTrue(asyncio.run(sf.refresh("u", path)))
            self.assertTrue(os.path.exists(path))
            sf2 = shadowfleet.ShadowFleet()
            with mock.patch.object(shadowfleet, "fetch", mock.AsyncMock(side_effect=OSError)):
                self.assertFalse(asyncio.run(sf2.refresh("u", path)))
            self.assertIsNotNone(sf2.match("9562233", ""))

    def test_legacy_env(self) -> None:
        with mock.patch.dict("os.environ", {"UPDATE_RATE": "7"}, clear=True):
            self.assertEqual(feeder.Settings.from_env().send.moving, 7.0)
        with mock.patch.dict("os.environ", {"AIS_AFFIL_OVERRIDES": "538:s, 626:suspect"},
                             clear=True):
            self.assertEqual(feeder.Settings.from_env().affil_overrides,
                             {"538": "s", "626": "s"})


if __name__ == "__main__":
    unittest.main()
