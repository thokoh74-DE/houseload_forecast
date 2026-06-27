"""Button-Plattform für Hauslast Prognose – SOC-Snapshot neu berechnen."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Entity-ID des Snapshot-Sensors – wird für den Lookup benötigt
_SNAPSHOT_SENSOR_ID = "sensor.hlf_diag_soc_prognose_midnight"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([SnapshotRefreshButton(hass, entry)])


class SnapshotRefreshButton(ButtonEntity):
    """Button: SOC-Prognose-Snapshot jetzt neu berechnen und speichern.

    Löscht den eingefrorenen Snapshot des aktuellen Tages und erzwingt
    eine sofortige Neuberechnung aus den aktuellen soc_forecast-Daten
    des Coordinators. Nützlich wenn die Prognose nach einer manuellen
    Korrektur oder einem Neustart aktualisiert werden soll.

    entity_id: button.hlf_soc_snapshot_refresh
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_soc_snapshot_refresh_{entry.entry_id}"
        self.entity_id = "button.hlf_soc_snapshot_refresh"

    @property
    def name(self) -> str:
        lang = self._hass.config.language
        if lang.startswith("de"):
            return "SOC-Prognose Snapshot neu berechnen"
        return "Refresh SOC Forecast Snapshot"

    @property
    def device_info(self):
        """Gleiche Geräte-Zuordnung wie die Sensoren."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
        }

    async def async_press(self) -> None:
        """Snapshot-Sensor suchen und Neuberechnung erzwingen."""
        # Snapshot-Sensor über die Entity-Komponente suchen
        component = self._hass.data.get("entity_components", {}).get("sensor")
        if component is None:
            _LOGGER.warning(
                "SnapshotRefreshButton: Sensor-Komponente nicht gefunden"
            )
            return

        snapshot_entity = None
        for entity in component.entities:
            if entity.entity_id == _SNAPSHOT_SENSOR_ID:
                snapshot_entity = entity
                break

        if snapshot_entity is None:
            _LOGGER.warning(
                "SnapshotRefreshButton: %s nicht gefunden", _SNAPSHOT_SENSOR_ID
            )
            return

        # Snapshot-Datum zurücksetzen → nächster native_value-Aufruf löst Neuberechnung aus
        snapshot_entity._snapshot_date = ""
        snapshot_entity._snapshot = {}

        # Sofortige Neuberechnung anstoßen
        snapshot_entity._maybe_take_snapshot()

        # Cache auf Disk schreiben
        await self._hass.async_add_executor_job(
            snapshot_entity._save_snapshot_to_disk
        )

        # State aktualisieren
        snapshot_entity.async_write_ha_state()

        _LOGGER.info(
            "SnapshotRefreshButton: SOC-Prognose-Snapshot wurde neu berechnet "
            "(%d Slots)", len(snapshot_entity._snapshot)
        )
