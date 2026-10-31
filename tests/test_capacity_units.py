"""Capacity-unit regressions using real HA states and the full coordinator.

Run with Home Assistant installed: python -m unittest discover -s tests -v
Recorder and cache paths are redirected to temporary fixture files.
"""

from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, State

from custom_components.houseload_forecast import sensor
from custom_components.houseload_forecast.const import (
    CONF_BAT_CAPACITY_SENSOR,
    CONF_BAT_CUTOFF_SENSOR,
    CONF_BAT_SOC_SENSOR,
    CONF_HAUSLAST_AKTUELL,
)

_MISSING_UNIT = object()


class CapacityUnitTests(unittest.IsolatedAsyncioTestCase):
    """Exercise energy scaling and the existing invalid-input lifecycle."""

    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capacity-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = patch.multiple(
            sensor,
            DB_PATH=str(root / "recorder.db"),
            _CACHE_SOC=str(root / "soc.json"),
            _CACHE_HL=str(root / "load.json"),
        )
        paths.start()
        self.addCleanup(paths.stop)
        with closing(sqlite3.connect(sensor.DB_PATH)) as database:
            database.executescript(
                "CREATE TABLE statistics_meta(id INTEGER, statistic_id TEXT, has_mean INTEGER, has_sum INTEGER);"
                "CREATE TABLE statistics(metadata_id INTEGER, start_ts REAL, mean REAL, sum REAL);"
            )
        self.now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
        clock = patch.object(sensor.dt_util, "now", return_value=self.now)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.hass = HomeAssistant(str(root))
        self.addAsyncCleanup(self.hass.async_stop)
        self.hass.states.async_set("sensor.soc", "55.8", {ATTR_UNIT_OF_MEASUREMENT: "%"})
        self.hass.states.async_set("sensor.cutoff", "10", {ATTR_UNIT_OF_MEASUREMENT: "%"})
        self.hass.states.async_set("sensor.load", "500", {ATTR_UNIT_OF_MEASUREMENT: "W"})
        self.cfg = {
            CONF_BAT_CAPACITY_SENSOR: "sensor.capacity",
            CONF_BAT_SOC_SENSOR: "sensor.soc",
            CONF_BAT_CUTOFF_SENSOR: "sensor.cutoff",
            CONF_HAUSLAST_AKTUELL: "sensor.load",
        }
        self.coordinator = self.new_coordinator()

    def new_coordinator(self):
        return sensor.HauslastCoordinator(self.hass, self.cfg, [500] * 24, [500] * 24)

    def set_capacity(self, value: str, unit: object = _MISSING_UNIT):
        attributes = {} if unit is _MISSING_UNIT else {ATTR_UNIT_OF_MEASUREMENT: unit}
        self.hass.states.async_set("sensor.capacity", value, attributes)

    def forecast_snapshot(self):
        coordinator = self.coordinator
        return copy.deepcopy({
            field: getattr(coordinator, field)
            for field in (
                "bat_max_kwh", "bat_kwh", "bat_rest_kwh", "cutoff_kwh",
                "restlaufzeit_min", "bat_only_runtime_min", "battery_empty_at",
                "forecast_heute", "forecast_morgen", "forecast_uebermorgen", "soc_forecast",
            )
        })

    async def test_wh_capacity_matches_documented_kwh_forecast(self):
        self.set_capacity("11.059", "kWh")
        await self.coordinator.async_refresh()
        control = self.forecast_snapshot()
        self.set_capacity("11059", "Wh")
        self.coordinator = self.new_coordinator()
        await self.coordinator.async_refresh()
        self.assertEqual(self.forecast_snapshot(), control)
        self.assertAlmostEqual(self.coordinator.bat_max_kwh, 11.059)
        self.assertAlmostEqual(self.coordinator.bat_kwh, 6.170922)
        self.assertAlmostEqual(self.coordinator.bat_rest_kwh, 5.065022)
        self.assertEqual(self.coordinator.bat_only_runtime_min, 607)

    async def test_energy_prefixes_and_joules_convert_to_kwh(self):
        for value, unit in (("11059000", "mWh"), ("0.011059", "MWh"), ("39812400", "J")):
            with self.subTest(unit=unit):
                self.set_capacity(value, unit)
                self.coordinator = self.new_coordinator()
                await self.coordinator.async_refresh()
                self.assertAlmostEqual(self.coordinator.bat_max_kwh, 11.059)
                self.assertAlmostEqual(self.coordinator.bat_rest_kwh, 5.065022)
                self.assertTrue(self.coordinator._has_valid_data)

    async def test_kwh_and_unitless_sensors_keep_existing_values(self):
        for unit in ("kWh", _MISSING_UNIT, None, ""):
            with self.subTest(unit=unit):
                self.set_capacity("11.059", unit)
                self.coordinator = self.new_coordinator()
                await self.coordinator.async_refresh()
                self.assertEqual(self.coordinator.bat_max_kwh, 11.059)
                self.assertAlmostEqual(self.coordinator.bat_rest_kwh, 5.065022)
                self.assertEqual(self.coordinator.hauslast_aktuell_kw, 0.5)
                self.assertEqual(self.coordinator.soc_pct_raw, 55.8)
                self.assertEqual(self.coordinator.cutoff_pct_raw, 10.0)

    async def test_incompatible_or_malformed_units_skip_initial_forecast(self):
        for unit in ("W", "%", "KWH", "unexpected", 123, ["Wh"], {"unit": "Wh"}):
            with self.subTest(unit=unit):
                self.set_capacity("11059", unit)
                self.coordinator = self.new_coordinator()
                with self.assertLogs(sensor._LOGGER, level="WARNING") as messages:
                    await self.coordinator.async_refresh()
                self.assertIn("sensor.capacity", messages.output[0])
                self.assertFalse(self.coordinator._has_valid_data)
                self.assertEqual(self.coordinator.bat_max_kwh, 0.0)
                self.assertEqual(self.coordinator.soc_forecast, [])

    async def test_missing_unavailable_and_malformed_values_skip_initial_forecast(self):
        for value in (None, "unknown", "unavailable", "", "not-a-number", "0", "-1"):
            with self.subTest(value=value):
                if value is None:
                    self.hass.states.async_remove("sensor.capacity")
                else:
                    self.set_capacity(value, "Wh")
                self.coordinator = self.new_coordinator()
                await self.coordinator.async_refresh()
                self.assertFalse(self.coordinator._has_valid_data)
                self.assertEqual(self.coordinator.bat_max_kwh, 0.0)

    async def test_capacity_numeric_boundaries_do_not_overflow(self):
        for value, unit in (("nan", "Wh"), ("inf", "kWh"), ("-inf", "Wh"), ("1e308", "MWh")):
            with self.subTest(value=value, unit=unit):
                self.set_capacity(value, unit)
                self.coordinator = self.new_coordinator()
                await self.coordinator.async_refresh()
                self.assertFalse(self.coordinator._has_valid_data)
                self.assertEqual(self.coordinator.bat_max_kwh, 0.0)
        for value, unit in (("1e308", "kWh"), ("1e304", "MWh")):
            with self.subTest(finite_value=value, unit=unit):
                self.set_capacity(value, unit)
                self.coordinator = self.new_coordinator()
                await self.coordinator.async_refresh()
                self.assertTrue(self.coordinator._has_valid_data)
                self.assertEqual(self.coordinator.bat_only_runtime_min, 2880)

    async def test_capacity_value_and_unit_use_one_state_snapshot(self):
        reads = []
        first = State("sensor.capacity", "11059", {ATTR_UNIT_OF_MEASUREMENT: "Wh"})
        second = State("sensor.capacity", "11.059", {ATTR_UNIT_OF_MEASUREMENT: "kWh"})
        original = self.hass.states.get

        def get_state(entity_id):
            if entity_id == "sensor.capacity":
                reads.append(entity_id)
                return first if len(reads) == 1 else second
            return original(entity_id)

        with patch.object(type(self.hass.states), "get", side_effect=get_state):
            await self.coordinator.async_refresh()
        self.assertEqual(len(reads), 1)
        self.assertAlmostEqual(self.coordinator.bat_max_kwh, 11.059)

    async def test_actual_ha_publication_preserves_retention_and_recovers(self):
        entry = SimpleNamespace(entry_id="capacity_test")
        runtime = sensor.AkkuRestlaufzeitSensor(self.coordinator, entry)
        capacity = sensor.DiagnosticSensor(self.coordinator, entry, "bat_max_kwh", "Capacity", "kWh", None, None)
        # Bind actual HA entities for publication without claiming platform/config-entry setup coverage.
        for entity in (runtime, capacity):
            entity.hass = self.hass
            entity._verified_state_writable = True
            entity._unit_of_measurement_translation_key = None
        self.coordinator.async_register_entities([runtime, capacity])

        self.set_capacity("11059", "W")
        with self.assertLogs(sensor._LOGGER, level="WARNING"):
            await self.coordinator.async_refresh()
        self.assertEqual(self.hass.states.get(runtime.entity_id).state, "unavailable")
        self.assertEqual(self.hass.states.get(capacity.entity_id).state, "unavailable")

        self.set_capacity("11059", "Wh")
        await self.coordinator.async_refresh()
        valid_runtime = self.hass.states.get(runtime.entity_id).state
        self.assertNotEqual(valid_runtime, "unavailable")
        self.assertEqual(self.hass.states.get(capacity.entity_id).state, "11.059")
        valid_forecast = self.forecast_snapshot()
        for unit in ("kWh", _MISSING_UNIT, None, ""):
            with self.subTest(published_control_unit=unit):
                self.set_capacity("11.059", unit)
                await self.coordinator.async_refresh()
                self.assertEqual(self.forecast_snapshot(), valid_forecast)
                self.assertEqual(self.hass.states.get(runtime.entity_id).state, valid_runtime)
                self.assertEqual(self.hass.states.get(capacity.entity_id).state, "11.059")

        self.clock.return_value = self.now + timedelta(minutes=1)
        self.set_capacity("11059", "W")
        with self.assertLogs(sensor._LOGGER, level="WARNING"):
            await self.coordinator.async_refresh()
        self.assertEqual(self.forecast_snapshot(), valid_forecast)
        self.assertTrue(runtime.available)
        retained = self.hass.states.get(runtime.entity_id)
        self.assertEqual(retained.state, valid_runtime)
        self.assertEqual(retained.attributes["diag_bat_kapazitaet_kwh"], 0.0)
        # Existing behavior: the timestamp advances even when the prior forecast is retained.
        self.assertEqual(retained.attributes["calculation_timestamp"], "2026-10-31 12:01:00")

        self.set_capacity("22000", "Wh")
        await self.coordinator.async_refresh()
        self.assertEqual(self.hass.states.get(capacity.entity_id).state, "22.0")
        self.assertAlmostEqual(self.coordinator.bat_rest_kwh, 10.076)


if __name__ == "__main__":
    unittest.main()
