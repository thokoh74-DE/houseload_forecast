"""Config flow for Hauslast Prognose integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_BAT_CAPACITY_SENSOR,
    CONF_BAT_SOC_SENSOR,
    CONF_BAT_CUTOFF_SENSOR,
    CONF_PV_TODAY_SENSOR,
    CONF_PV_TOMORROW_SENSOR,
    CONF_FORCE_EXPORT_BOOLEAN,
    CONF_FORCE_EXPORT_POWER,
    CONF_HAUSLAST_STUNDLICH,
    CONF_HISTORY_WEEKS,
    DEFAULT_HISTORY_WEEKS,
    DEFAULT_FALLBACK_WT,
    DEFAULT_FALLBACK_WE,
    FALLBACK_WT_KEYS,
    FALLBACK_WE_KEYS,
)


def _sensor_selector():
    return selector.selector({"entity": {"domain": "sensor"}})

def _number_selector_w():
    return selector.selector({"number": {"min": 0, "max": 5000, "step": 10,
                                          "unit_of_measurement": "W", "mode": "box"}})

def _history_weeks_selector():
    return selector.selector({"number": {"min": 0, "max": 9999, "step": 1,
                                          "unit_of_measurement": "Wochen", "mode": "box"}})

def _entity_selector(domain):
    return selector.selector({"entity": {"domain": domain}})


def _sensors_schema(data: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_BAT_CAPACITY_SENSOR,
                     default=data.get(CONF_BAT_CAPACITY_SENSOR, "sensor.alb002022083046_current_capacity")): _sensor_selector(),
        vol.Required(CONF_BAT_SOC_SENSOR,
                     default=data.get(CONF_BAT_SOC_SENSOR, "sensor.alphaess_soc_battery")): _sensor_selector(),
        vol.Required(CONF_BAT_CUTOFF_SENSOR,
                     default=data.get(CONF_BAT_CUTOFF_SENSOR, "sensor.alphaess_discharging_cutoff_soc")): _sensor_selector(),
        vol.Required(CONF_PV_TODAY_SENSOR,
                     default=data.get(CONF_PV_TODAY_SENSOR, "sensor.solcast_pv_forecast_prognose_heute")): _sensor_selector(),
        vol.Required(CONF_PV_TOMORROW_SENSOR,
                     default=data.get(CONF_PV_TOMORROW_SENSOR, "sensor.solcast_pv_forecast_prognose_morgen")): _sensor_selector(),
        vol.Optional(CONF_FORCE_EXPORT_BOOLEAN,
                     default=data.get(CONF_FORCE_EXPORT_BOOLEAN, vol.UNDEFINED)): _entity_selector("input_boolean"),
        vol.Optional(CONF_FORCE_EXPORT_POWER,
                     default=data.get(CONF_FORCE_EXPORT_POWER, vol.UNDEFINED)): _entity_selector("number"),
        vol.Required(CONF_HAUSLAST_STUNDLICH,
                     default=data.get(CONF_HAUSLAST_STUNDLICH, "sensor.hauslast_stundlich")): _sensor_selector(),
        vol.Required(CONF_HISTORY_WEEKS,
                     default=int(data.get(CONF_HISTORY_WEEKS, DEFAULT_HISTORY_WEEKS))): _history_weeks_selector(),
    })


def _fallback_wt_schema(defaults_wt) -> vol.Schema:
    """Schema für Wochentag-Fallbackprofil (Mo–Fr)."""
    fields = {}
    for h, key in enumerate(FALLBACK_WT_KEYS):
        fields[vol.Required(key, default=int(defaults_wt[h]))] = _number_selector_w()
    return vol.Schema(fields)


def _fallback_we_schema(defaults_we) -> vol.Schema:
    """Schema für Wochenende-Fallbackprofil (Sa+So)."""
    fields = {}
    for h, key in enumerate(FALLBACK_WE_KEYS):
        fields[vol.Required(key, default=int(defaults_we[h]))] = _number_selector_w()
    return vol.Schema(fields)


class HauslastPrognoseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Ersteinrichtung: Sensoren → Fallback Wochentag → Fallback Wochenende."""

    VERSION = 1
    _user_data: dict = {}
    TRANSLATION_DOMAIN = DOMAIN

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._user_data = dict(user_input)
            return await self.async_step_fallback_wt()
        return self.async_show_form(
            step_id="user",
            data_schema=_sensors_schema({}),
        )

    async def async_step_fallback_wt(self, user_input=None):
        """Schritt 2: Fallback-Profil Wochentag (Mo–Fr)."""
        if user_input is not None:
            self._user_data.update(user_input)
            return await self.async_step_fallback_we()
        return self.async_show_form(
            step_id="fallback_wt",
            data_schema=_fallback_wt_schema(DEFAULT_FALLBACK_WT),
        )

    async def async_step_fallback_we(self, user_input=None):
        """Schritt 3: Fallback-Profil Wochenende (Sa+So)."""
        if user_input is not None:
            self._user_data.update(user_input)
            return self.async_create_entry(
                title="Hauslast Prognose & Akku Restlaufzeit",
                data=self._user_data,
            )
        return self.async_show_form(
            step_id="fallback_we",
            data_schema=_fallback_we_schema(DEFAULT_FALLBACK_WE),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HauslastPrognoseOptionsFlow(config_entry)


class HauslastPrognoseOptionsFlow(config_entries.OptionsFlow):
    """Options: Menü → Sensoren ODER Fallback Wochentag → Wochenende."""

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._pending: dict = {}

    def _current_data(self) -> dict:
        return {**self._config_entry.data, **self._config_entry.options}

    # ── Menü ──────────────────────────────────────────────────────────
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["sensors", "fallback_wt"],
        )

    # ── Sensoren ──────────────────────────────────────────────────────
    async def async_step_sensors(self, user_input=None):
        if user_input is not None:
            updated = {**self._current_data(), **user_input}
            return self.async_create_entry(title="", data=updated)
        return self.async_show_form(
            step_id="sensors",
            data_schema=_sensors_schema(self._current_data()),
        )

    # ── Fallback Wochentag ────────────────────────────────────────────
    async def async_step_fallback_wt(self, user_input=None):
        """Wochentag-Profil bearbeiten, danach weiter zu Wochenende."""
        if user_input is not None:
            self._pending = dict(user_input)
            return await self.async_step_fallback_we()
        data = self._current_data()
        defaults_wt = [data.get(k, DEFAULT_FALLBACK_WT[h]) for h, k in enumerate(FALLBACK_WT_KEYS)]
        return self.async_show_form(
            step_id="fallback_wt",
            data_schema=_fallback_wt_schema(defaults_wt),
        )

    # ── Fallback Wochenende ───────────────────────────────────────────
    async def async_step_fallback_we(self, user_input=None):
        """Wochenende-Profil bearbeiten, dann speichern."""
        if user_input is not None:
            updated = {**self._current_data(), **self._pending, **user_input}
            return self.async_create_entry(title="", data=updated)
        data = self._current_data()
        defaults_we = [data.get(k, DEFAULT_FALLBACK_WE[h]) for h, k in enumerate(FALLBACK_WE_KEYS)]
        return self.async_show_form(
            step_id="fallback_we",
            data_schema=_fallback_we_schema(defaults_we),
        )
