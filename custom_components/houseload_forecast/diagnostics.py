"""Diagnostics support for House Load Forecast."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

REDACT_KEYS: set[str] = set()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    config = dict(entry.data)
    for key in REDACT_KEYS:
        if key in config:
            config[key] = "**REDACTED**"

    # Coordinator-Daten sammeln (falls vorhanden)
    coordinator_data: dict[str, Any] = {}
    # Die Sensoren werden über den Coordinator gesteuert;
    # wir sammeln die wichtigsten Zustandswerte.
    for entity_id in [
        "sensor.hlf_battery_runtime",
        "sensor.hlf_forecast_today",
        "sensor.hlf_diag_soc_aktuell",
        "sensor.hlf_diag_bat_rest_kwh",
    ]:
        state = hass.states.get(entity_id)
        if state:
            coordinator_data[entity_id] = {
                "state": state.state,
                "attributes": {
                    k: v for k, v in state.attributes.items()
                    if k not in ("soc_hourly_forecast", "soc_kwh_cutoff", "forecast", "snapshot")
                },
            }

    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "data": config,
            "options": dict(entry.options),
        },
        "sensors": coordinator_data,
    }
