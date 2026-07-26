"""Sensor platform für Hauslast Prognose & Akku Restlaufzeit."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAT_CAPACITY_SENSOR,
    CONF_BAT_CUTOFF_SENSOR,
    CONF_BAT_SOC_SENSOR,
    CONF_FORCE_EXPORT_BOOLEAN,
    CONF_FORCE_EXPORT_POWER,
    CONF_HAUSLAST_AKTUELL,
    CONF_HISTORY_WEEKS,
    CONF_PV_DAY_AFTER_TOMORROW_SENSOR,
    CONF_PV_TODAY_SENSOR,
    CONF_PV_TOMORROW_SENSOR,
    CONF_RUNTIME_BUFFER_PCT,
    DEFAULT_FALLBACK_WE,
    DEFAULT_FALLBACK_WT,
    DEFAULT_HISTORY_WEEKS,
    DEFAULT_RUNTIME_BUFFER_PCT,
    DOMAIN,
    FALLBACK_WE_KEYS,
    FALLBACK_WT_KEYS,
    GENERATED_HAUSLAST_DAILY_ID,
    GENERATED_HAUSLAST_SENSOR_ID,
    MIN_DATA_DAYS,
    WEEKDAY_NAMES,
)

_LOGGER = logging.getLogger(__name__)

DB_PATH = "/config/home-assistant_v2.db"

# Maximale Restlaufzeit in Minuten (48 h) – wird als "Akku reicht durch" interpretiert
MAX_RUNTIME_MIN = 2880

# Persistente Cache-Dateien unter /config/.storage/
_CACHE_SOC   = "/config/.storage/houseload_forecast_soc_cache.json"
_CACHE_HL    = "/config/.storage/houseload_forecast_hl_cache.json"

# ── Übersetzungs-Hilfsfunktion ────────────────────────────────────────────────
_SENSOR_NAMES_DE = {
    "forecast_today":             "Hauslast-Prognose Heute",
    "forecast_tomorrow":          "Hauslast-Prognose Morgen",
    "forecast_day_after_tomorrow": "Hauslast-Prognose Übermorgen",
    "forecast_current_hour":      "Hauslast-Prognose Aktuelle Stunde",
    "forecast_next_hour":         "Hauslast-Prognose Nächste Stunde",
    "battery_runtime":            "PV Akku Restlaufzeit",
    "fallback_weekday":           "Hauslast Fallback Wochentag",
    "fallback_weekend":           "Hauslast Fallback Wochenende",
    "diag_calculation_timestamp": "Letzte Aktualisierung",
    "diag_data_days":             "Anzahl Tage Datenbasis",
    "diag_bat_max_kwh":           "Effektive Batteriekapazität",
    "diag_bat_kwh":               "Nutzbare Kapazität",
    "diag_bat_rest_kwh":          "Restkapazität bis CutOff",
    "diag_force_on":              "Force-Export aktiv",
    "diag_battery_empty_at":      "Akku leer um",
    "diag_forecast_mae_today":    "Ø Abweichung Prognose Heute",
    "diag_soc_prognose_midnight": "SOC-Prognose",
    "diag_soc_aktuell":           "Batterieladezustand",
}

_SENSOR_NAMES_EN = {
    "forecast_today":             "House Load Forecast Today",
    "forecast_tomorrow":          "House Load Forecast Tomorrow",
    "forecast_day_after_tomorrow": "House Load Forecast Day After Tomorrow",
    "forecast_current_hour":      "Forecast Current Hour",
    "forecast_next_hour":         "Forecast Next Hour",
    "battery_runtime":            "PV Battery Runtime",
    "fallback_weekday":           "House Load Fallback Weekday",
    "fallback_weekend":           "House Load Fallback Weekend",
    "diag_calculation_timestamp": "Last Forecast Update",
    "diag_data_days":             "Data History Days",
    "diag_bat_max_kwh":           "Effective Battery Capacity",
    "diag_bat_kwh":               "Usable Capacity",
    "diag_bat_rest_kwh":          "Remaining Capacity to Cutoff",
    "diag_force_on":              "Force Export Active",
    "diag_battery_empty_at":      "Battery Empty At",
    "diag_forecast_mae_today":    "Forecast MAE Today",
    "diag_soc_prognose_midnight": "SOC Forecast",
    "diag_soc_aktuell":           "Battery State of Charge",
}

def _get_sensor_name(hass_or_none, translation_key: str) -> str:
    """Liefert den Sensor-Namen passend zur HA-Systemsprache."""
    try:
        lang = hass_or_none.config.language if hass_or_none else "en"
    except Exception:
        lang = "en"
    if lang.startswith("de"):
        return _SENSOR_NAMES_DE.get(translation_key, translation_key)
    return _SENSOR_NAMES_EN.get(translation_key, translation_key)


# Python weekday(): 0=Mo, 1=Di, 2=Mi, 3=Do, 4=Fr, 5=Sa, 6=So
# SQLite strftime('%w'): 0=So, 1=Mo, 2=Di, 3=Mi, 4=Do, 5=Fr, 6=Sa
_SQLITE_DOW_TO_PY = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    cfg = hass.data[DOMAIN][entry.entry_id]

    fallback_wt = [cfg.get(k, DEFAULT_FALLBACK_WT[h]) for h, k in enumerate(FALLBACK_WT_KEYS)]
    fallback_we = [cfg.get(k, DEFAULT_FALLBACK_WE[h]) for h, k in enumerate(FALLBACK_WE_KEYS)]

    coordinator = HauslastCoordinator(hass, cfg, fallback_wt, fallback_we)
    await coordinator.async_refresh()

    # NEU v1.1.2: Verbrauchszähler-Sensor (aus aktueller Leistung abgeleitet)
    hauslast_stundlich_sensor = HauslastStundlichSensor(entry)
    hauslast_taeglich_sensor = HauslastTaeglichSensor(entry)

    sensors = [
        hauslast_stundlich_sensor,
        hauslast_taeglich_sensor,
        HauslastFallbackSensor(coordinator, "wochentag", entry),
        HauslastFallbackSensor(coordinator, "wochenende", entry),
        HauslastPrognoseHeuteSensor(coordinator, entry),
        HauslastPrognoseMorgenSensor(coordinator, entry),
        HauslastPrognoseUebermorgenSensor(coordinator, entry),
        ForecastCurrentHourSensor(coordinator, entry),
        ForecastNextHourSensor(coordinator, entry),
        AkkuRestlaufzeitSensor(coordinator, entry),
        DiagnosticSensor(coordinator, entry, "calculation_timestamp",
                         "Last Forecast Update", None, None, "mdi:clock-outline"),
        DiagnosticSensor(coordinator, entry, "data_days",
                         "Data History Days", "d", None, "mdi:database-clock"),
        DiagnosticSensor(coordinator, entry, "bat_max_kwh",
                         "Effective Battery Capacity", "kWh", None, "mdi:battery-high"),
        DiagnosticSensor(coordinator, entry, "bat_kwh",
                         "Usable Capacity", "kWh", None, "mdi:battery-arrow-up"),
        DiagnosticSensor(coordinator, entry, "bat_rest_kwh",
                         "Remaining Capacity to Cutoff", "kWh", None, "mdi:battery-arrow-down-outline"),
        DiagnosticSensor(coordinator, entry, "force_on",
                         "Force Export Active", None, None, "mdi:transmission-tower-export"),
        DiagnosticSensor(coordinator, entry, "battery_empty_at",
                         "Battery Empty At", None, None, "mdi:battery-alert"),
        DiagnosticSensor(coordinator, entry, "forecast_mae_today",
                         "Forecast MAE Today", "kWh", None, "mdi:chart-bell-curve-cumulative"),
        SocPrognoseAtMidnightSensor(coordinator, entry),
        SocAktuellStatistikSensor(coordinator, entry),
    ]

    async_add_entities(sensors, True)
    # NEU v2.1.1: hauslast_stundlich/taeglich werden bewusst NICHT beim Coordinator
    # registriert. Sie verwalten ihren eigenen Recorder-Write vollständig selbst
    # (siehe handle_power_update, WRITE_MIN_INTERVAL_S). Wären sie hier registriert,
    # würde jeder Coordinator-Refresh sie zusätzlich unthrottled schreiben – und da
    # ihre eigene Entity-ID in watch_forecast steht, entsteht dadurch ein
    # sich selbst antreibender ~5s-Feedback-Loop, der den Write-Throttle umgeht.
    coordinator.async_register_entities(
        [s for s in sensors if s not in (hauslast_stundlich_sensor, hauslast_taeglich_sensor)]
    )

    # Forecast-Neuberechnung bei Änderung der Eingangssensoren
    watch_forecast = [
        cfg.get(CONF_BAT_CAPACITY_SENSOR),
        cfg.get(CONF_BAT_SOC_SENSOR),
        cfg.get(CONF_BAT_CUTOFF_SENSOR),
        cfg.get(CONF_PV_TODAY_SENSOR),
        cfg.get(CONF_PV_TOMORROW_SENSOR),
        cfg.get(CONF_PV_DAY_AFTER_TOMORROW_SENSOR),
        cfg.get(CONF_FORCE_EXPORT_BOOLEAN),
        cfg.get(CONF_FORCE_EXPORT_POWER),
        GENERATED_HAUSLAST_SENSOR_ID,
    ]
    watch_forecast = [e for e in watch_forecast if e]

    # Debounce: Forecast-Neuberechnung max. alle 5 s nach letztem State-Change
    # Verhindert vielfachen _compute()-Aufruf wenn AlphaESS mehrere Sensoren
    # gleichzeitig aktualisiert.
    _debounce_handle: list = [None]

    @callback
    def _state_changed(event):
        if _debounce_handle[0] is not None:
            _debounce_handle[0].cancel()
        _debounce_handle[0] = hass.loop.call_later(5.0, _trigger_refresh)

    def _trigger_refresh():
        _debounce_handle[0] = None
        coordinator.async_update_all()

    entry.async_on_unload(
        async_track_state_change_event(hass, watch_forecast, _state_changed)
    )

    # 30-Sekunden-Interval: Prognose und Restlaufzeit werden regelmaessig
    # aktualisiert, auch ohne eingehende State-Changes (z.B. nachts)
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda _: coordinator.async_update_all(),
            timedelta(seconds=30),
        )
    )

    # Leistungssensor -> Verbrauchszaehler akkumulieren (event-getrieben, kein Debounce)
    aktuell_entity = cfg.get(CONF_HAUSLAST_AKTUELL)
    if aktuell_entity:
        @callback
        def _aktuell_changed(event):
            hauslast_stundlich_sensor.handle_power_update(hass, aktuell_entity)
            hauslast_taeglich_sensor.handle_power_update(hass, aktuell_entity)

        entry.async_on_unload(
            async_track_state_change_event(hass, [aktuell_entity], _aktuell_changed)
        )


class HauslastCoordinator:
    """Central data coordinator."""

    def __init__(self, hass, cfg, fallback_wt, fallback_we):
        self.hass = hass
        self.cfg = cfg
        self.fallback_wt = fallback_wt
        self.fallback_we = fallback_we
        self._entities: list = []

        self.profiles: list[list[float]] = [[] for _ in range(7)]
        self.profile_sources: list[str] = [""] * 7

        self.profile_wt: list[float] = []
        self.profile_we: list[float] = []
        self.profile_source_wt: str = ""
        self.profile_source_we: str = ""

        self.forecast_heute: list[dict] = []
        self.forecast_morgen: list[dict] = []
        self.forecast_uebermorgen: list[dict] = []
        self.soc_forecast: list[dict] = []
        self.restlaufzeit_min: int = 0
        self.bat_kwh: float = 0.0
        self.bat_max_kwh: float = 0.0
        self.data_days: int = 0
        self.history_weeks_used: int = 0
        self.calculation_timestamp: str = ""

        self.bat_capacity_raw: float = 0.0
        self.soc_pct_raw: float = 0.0
        self.cutoff_pct_raw: float = 0.0
        self.usable_pct: float = 0.0
        self.force_on: bool = False
        self.force_kwh: float = 0.0
        self.pv_hours_today_count: int = 0
        self.pv_hours_morgen_count: int = 0
        self.pv_hours_day_after_count: int = 0
        self.hauslast_slots_heute: int = 0
        self.hauslast_slots_morgen: int = 0
        self.hauslast_slots_uebermorgen: int = 0
        self.soc_slots_processed: int = 0
        self.bat_rest_kwh: float = 0.0
        self.cutoff_kwh: float = 0.0
        self.forecast_mae_today: float = 0.0

        # NEU: Zeitpunkt Akku leer (None = reicht durch, False wenn MAX_RUNTIME)
        self.battery_empty_at: str | bool = False

        # Akku-Only-Restlaufzeit: Wie lange reicht der Akku ohne PV?
        self.bat_only_runtime_min: int = 0

        self._has_valid_data: bool = False

        # Cache wird beim ersten _compute()-Aufruf im Executor geladen.
        # __init__ laeuft im Event Loop und darf kein blockierendes I/O machen.
        self._frozen_past_slots: list[dict] = []
        self._frozen_past_date: str = dt_util.now().strftime("%Y-%m-%d")
        self._frozen_hl_past_slots: dict[str, float] = {}
        self._frozen_hl_past_date: str = dt_util.now().strftime("%Y-%m-%d")
        self._cache_loaded: bool = False

    def async_register_entities(self, entities):
        self._entities = entities

    @staticmethod
    def _load_cache(path: str, default):
        """Cache aus JSON-Datei laden. Gibt default zurück wenn Datei fehlt oder defekt."""
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                # Nur Einträge vom heutigen Tag behalten
                today = dt_util.now().strftime("%Y-%m-%d")
                if isinstance(data, list):
                    return [e for e in data
                            if e.get("period_start", "").startswith(today)]
                if isinstance(data, dict):
                    return {k: v for k, v in data.items()
                            if k.startswith(today)}
        except Exception as exc:
            _LOGGER.debug("Cache-Datei konnte nicht geladen werden (%s): %s", path, exc)
        return default

    @staticmethod
    def _save_cache(path: str, data) -> None:
        """Cache als JSON-Datei speichern."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as exc:
            _LOGGER.debug("Cache-Datei konnte nicht gespeichert werden (%s): %s", path, exc)

    def async_update_all(self):
        # Thread-safe: call_soon_threadsafe stellt sicher dass async_create_task
        # immer aus dem Event Loop aufgerufen wird, unabhaengig vom Aufrufer-Kontext.
        self.hass.loop.call_soon_threadsafe(
            lambda: self.hass.async_create_task(self.async_refresh())
        )

    async def async_refresh(self):
        await self.hass.async_add_executor_job(self._compute)
        for entity in self._entities:
            if entity.hass is not None:
                entity.async_write_ha_state()

    def _get_state(self, entity_id: str, default=None):
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", ""):
            return default
        return state.state

    def _get_attr(self, entity_id: str, attr: str, default=None):
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if state is None:
            return default
        return state.attributes.get(attr, default)

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        val = self._get_state(entity_id)
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def _compute(self):
        import sqlite3

        # Cache einmalig beim ersten Executor-Aufruf laden (I/O hier erlaubt)
        if not self._cache_loaded:
            self._frozen_past_slots = self._load_cache(_CACHE_SOC, [])
            self._frozen_hl_past_slots = self._load_cache(_CACHE_HL, {})
            self._cache_loaded = True

        self.calculation_timestamp = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")

        # Vergangenheits-Cache täglich um Mitternacht leeren
        today_str = dt_util.now().strftime("%Y-%m-%d")
        if self._frozen_past_date != today_str:
            self._frozen_past_slots = []
            self._frozen_past_date = today_str
            self._save_cache(_CACHE_SOC, self._frozen_past_slots)

        # Hauslast-Vergangenheits-Cache täglich leeren
        if self._frozen_hl_past_date != today_str:
            self._frozen_hl_past_slots = {}
            self._frozen_hl_past_date = today_str
            self._save_cache(_CACHE_HL, self._frozen_hl_past_slots)


        raw_weeks = self.cfg.get(CONF_HISTORY_WEEKS, DEFAULT_HISTORY_WEEKS)
        try:
            history_weeks = int(raw_weeks)
        except (TypeError, ValueError):
            history_weeks = DEFAULT_HISTORY_WEEKS
        self.history_weeks_used = history_weeks

        if history_weeks > 0:
            history_days = history_weeks * 7
            history_param = f"-{history_days} days"
            history_label = f"letzte {history_weeks} Wochen"
        else:
            history_param = "-36500 days"
            history_label = "gesamte Datenbasis"

        # v1.1.2: Von der Integration erzeugter Verbrauchszähler
        statistic_id = GENERATED_HAUSLAST_SENSOR_ID

        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()

            cur.execute("""
                SELECT CAST(
                    ROUND(julianday('now','localtime') -
                          julianday(datetime(MIN(start_ts),'unixepoch','localtime')))
                AS INTEGER)
                FROM statistics
                WHERE metadata_id = (
                    SELECT id FROM statistics_meta WHERE statistic_id = ?
                )
            """, (statistic_id,))
            row = cur.fetchone()
            self.data_days = row[0] if row and row[0] else 0

            if self.data_days >= MIN_DATA_DAYS:
                cur.execute(
                    "SELECT has_mean, has_sum FROM statistics_meta WHERE statistic_id = ?",
                    (statistic_id,)
                )
                meta_row = cur.fetchone()
                sensor_has_mean = meta_row and meta_row[0] == 1

                if sensor_has_mean:
                    raw_sql = """
                        SELECT
                            CAST(strftime('%w', datetime(start_ts,'unixepoch','localtime')) AS INTEGER) AS sqlite_dow,
                            CAST(strftime('%H', datetime(start_ts,'unixepoch','localtime')) AS INTEGER) AS hour,
                            mean AS val
                        FROM statistics
                        WHERE metadata_id = (SELECT id FROM statistics_meta WHERE statistic_id = ?)
                          AND start_ts >= strftime('%s', datetime('now', ?))
                          AND mean IS NOT NULL AND mean >= 0
                        ORDER BY start_ts
                    """
                    value_col = "mean (W)"
                    scale = 1.0
                else:
                    # TOTAL_INCREASING-Zähler: stündliche Differenz via LAG(sum)
                    # sum[h] - sum[h-1] = Verbrauch der Stunde h in kWh → *1000 → W
                    raw_sql = """
                        SELECT
                            CAST(strftime('%w', datetime(start_ts,'unixepoch','localtime')) AS INTEGER) AS sqlite_dow,
                            CAST(strftime('%H', datetime(start_ts,'unixepoch','localtime')) AS INTEGER) AS hour,
                            (sum - LAG(sum) OVER (ORDER BY start_ts)) AS val
                        FROM statistics
                        WHERE metadata_id = (SELECT id FROM statistics_meta WHERE statistic_id = ?)
                          AND start_ts >= strftime('%s', datetime('now', ?))
                          AND sum IS NOT NULL
                        ORDER BY start_ts
                    """
                    value_col = "sum-diff (kWh→W)"
                    scale = 1000.0

                cur.execute(raw_sql, (statistic_id, history_param))
                all_rows = cur.fetchall()

                buckets: list[list[list[float]]] = [[[] for _ in range(24)] for _ in range(7)]
                for sqlite_dow, hour, val in all_rows:
                    if val is None or val < 0:
                        continue  # NULL (LAG erste Zeile) oder Zähler-Reset verwerfen
                    scaled = float(val) * scale
                    if scaled > 20000:
                        continue  # Ausreißer > 20 kW Durchschnitt ignorieren
                    py_wd = _SQLITE_DOW_TO_PY[int(sqlite_dow)]
                    buckets[py_wd][hour].append(scaled)

                def iqr_filtered_mean(values: list[float], fallback: float) -> float:
                    if not values:
                        return fallback
                    s = sorted(values)
                    n = len(s)
                    if n < 4:
                        return round(sum(s) / n, 2)
                    q1 = s[n // 4]
                    q3 = s[(3 * n) // 4]
                    iqr = q3 - q1
                    lo = q1 - 3.0 * iqr
                    hi = q3 + 3.0 * iqr
                    clean = [v for v in s if lo <= v <= hi]
                    if not clean:
                        return round(sum(s) / n, 2)
                    return round(sum(clean) / len(clean), 2)

                def fallback_for(py_wd: int) -> list[float]:
                    return self.fallback_we if py_wd >= 5 else self.fallback_wt

                for py_wd in range(7):
                    hours_with_data = sum(1 for h in range(24) if buckets[py_wd][h])
                    day_name = WEEKDAY_NAMES[py_wd].capitalize()
                    fb = fallback_for(py_wd)
                    if hours_with_data >= 12:
                        self.profiles[py_wd] = [
                            iqr_filtered_mean(buckets[py_wd][h], fb[h])
                            for h in range(24)
                        ]
                        self.profile_sources[py_wd] = (
                            f"Historisch ({history_label}, {value_col}, IQR-gefiltert)"
                        )
                    else:
                        self.profiles[py_wd] = list(fb)
                        self.profile_sources[py_wd] = (
                            f"Fallback (zu wenige Daten für {day_name}: {hours_with_data} Stunden)"
                        )

                def avg_profiles(weekdays: list[int]) -> list[float]:
                    result = []
                    for h in range(24):
                        vals = [self.profiles[d][h] for d in weekdays if self.profiles[d]]
                        result.append(round(sum(vals) / len(vals), 2) if vals else 0.0)
                    return result

                self.profile_wt = avg_profiles([0, 1, 2, 3, 4])
                self.profile_we = avg_profiles([5, 6])
                self.profile_source_wt = f"Ø Wochentage (Mo–Fr), {history_label}"
                self.profile_source_we = f"Ø Wochenende (Sa+So), {history_label}"

            else:
                for py_wd in range(7):
                    fb = self.fallback_we if py_wd >= 5 else self.fallback_wt
                    self.profiles[py_wd] = list(fb)
                    self.profile_sources[py_wd] = (
                        f"Fallback (nur {self.data_days} Tage Daten, min. {MIN_DATA_DAYS} erforderlich)"
                    )
                self.profile_wt = list(self.fallback_wt)
                self.profile_we = list(self.fallback_we)
                self.profile_source_wt = f"Fallback (nur {self.data_days} Tage)"
                self.profile_source_we = f"Fallback (nur {self.data_days} Tage)"

            con.close()

        except Exception as exc:
            _LOGGER.warning("DB-Fehler beim Lesen des Hauslast-Profils: %s – Fallback", exc)
            for py_wd in range(7):
                fb = self.fallback_we if py_wd >= 5 else self.fallback_wt
                self.profiles[py_wd] = list(fb)
                self.profile_sources[py_wd] = f"Fallback (DB-Fehler: {exc})"
            self.profile_wt = list(self.fallback_wt)
            self.profile_we = list(self.fallback_we)
            self.data_days = 0
            self.profile_source_wt = f"Fallback (DB-Fehler: {exc})"
            self.profile_source_we = f"Fallback (DB-Fehler: {exc})"

        # ── Batterie-Werte ─────────────────────────────────────────────
        self.bat_capacity_raw = self._get_float(self.cfg.get(CONF_BAT_CAPACITY_SENSOR))
        self.soc_pct_raw      = self._get_float(self.cfg.get(CONF_BAT_SOC_SENSOR))
        self.cutoff_pct_raw   = self._get_float(self.cfg.get(CONF_BAT_CUTOFF_SENSOR))

        bat_sensors_ready = (
            self.bat_capacity_raw > 0
            and self.soc_pct_raw > 0
        )
        if not bat_sensors_ready:
            _LOGGER.debug(
                "Batterie-Sensoren noch nicht verfügbar (capacity=%.1f, soc=%.1f) – "
                "überspringe Restlaufzeit-Berechnung",
                self.bat_capacity_raw, self.soc_pct_raw
            )
            return

        self.usable_pct   = max(self.soc_pct_raw - self.cutoff_pct_raw, 0.0)
        self.bat_max_kwh  = self.bat_capacity_raw
        self.bat_kwh      = self.soc_pct_raw / 100.0 * self.bat_max_kwh
        self.bat_rest_kwh = max(self.usable_pct / 100.0 * self.bat_max_kwh, 0.0)

        # ── Force Export ───────────────────────────────────────────────
        self.force_on = False
        fe_state = self._get_state(self.cfg.get(CONF_FORCE_EXPORT_BOOLEAN))
        if fe_state == "on":
            self.force_on = True
        self.force_kwh = self._get_float(self.cfg.get(CONF_FORCE_EXPORT_POWER)) if self.force_on else 0.0

        # ── Hauslast-Forecast aufbauen ─────────────────────────────────
        # FIX: Prognose von 00:00 Uhr heutigen Tages bis 23:00 Uhr morgen
        # Anzeige: 00:00 – aktuelle Stunde = Ist-Werte (SOC), Rest = Prognose
        now_local   = dt_util.now()
        today_wd    = now_local.weekday()
        tomorrow_wd = (today_wd + 1) % 7

        # Tagesbeginn heute 00:00
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        def build_forecast(profile: list[float], base_date) -> list[dict]:
            """Hauslast-Forecast aufbauen.
            Vergangene Stunden werden eingefroren – Parameteränderungen ändern sie nicht mehr.
            Aktuelle und zukünftige Stunden werden immer frisch berechnet.
            """
            result = []
            now_floor_h = now_local.replace(minute=0, second=0, microsecond=0)
            for h in range(24):
                dt_slot = base_date.replace(hour=h, minute=0, second=0, microsecond=0)
                ts_key = dt_slot.isoformat()
                load_w = profile[h] / 1000.0 if h < len(profile) else 0.0

                if dt_slot < now_floor_h:
                    # Vergangene Stunde: einmalig einfrieren, danach immer aus Cache
                    if ts_key not in self._frozen_hl_past_slots:
                        self._frozen_hl_past_slots[ts_key] = round(load_w, 3)
                        self._save_cache(_CACHE_HL, self._frozen_hl_past_slots)
                    result.append({
                        "period_start": ts_key,
                        "load_estimate": self._frozen_hl_past_slots[ts_key],
                    })
                else:
                    # Aktuelle und zukünftige Stunden: immer neu berechnen
                    result.append({
                        "period_start": ts_key,
                        "load_estimate": round(load_w, 3),
                    })
            return result

        day_after_wd = (today_wd + 2) % 7

        profile_heute       = self.profiles[today_wd]      if self.profiles[today_wd]      else self.fallback_wt
        profile_morgen      = self.profiles[tomorrow_wd]   if self.profiles[tomorrow_wd]   else self.fallback_wt
        profile_uebermorgen = self.profiles[day_after_wd]  if self.profiles[day_after_wd]  else self.fallback_wt

        # forecast_heute startet bei 00:00; vergangene Stunden werden eingefroren
        self.forecast_heute = build_forecast(profile_heute, today_start)
        self.forecast_morgen = build_forecast(
            profile_morgen,
            (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        )
        self.forecast_uebermorgen = build_forecast(
            profile_uebermorgen,
            (now_local + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        )
        self.hauslast_slots_heute      = len(self.forecast_heute)
        self.hauslast_slots_morgen     = len(self.forecast_morgen)
        self.hauslast_slots_uebermorgen = len(self.forecast_uebermorgen)

        # ── PV-Forecast aus Solcast-Attributen ────────────────────────
        pv_today_list     = self._get_attr(self.cfg.get(CONF_PV_TODAY_SENSOR),              "detailedHourly", []) or []
        pv_morgen_list    = self._get_attr(self.cfg.get(CONF_PV_TOMORROW_SENSOR),           "detailedHourly", []) or []
        pv_day_after_list = self._get_attr(self.cfg.get(CONF_PV_DAY_AFTER_TOMORROW_SENSOR), "detailedHourly", []) or []
        pv_hours = list(pv_today_list) + list(pv_morgen_list) + list(pv_day_after_list)
        self.pv_hours_today_count    = len(pv_today_list)
        self.pv_hours_morgen_count   = len(pv_morgen_list)
        self.pv_hours_day_after_count = len(pv_day_after_list)

        # Kombiniere heute + morgen + übermorgen für SOC-Simulation (72 h ab 00:00, davon 48 h ab jetzt)
        hl_hours = self.forecast_heute + self.forecast_morgen + self.forecast_uebermorgen
        pv_len = len(pv_hours)
        hl_len = len(hl_hours)
        # 72 Slots laden (3 Tage), SOC-Ausgabe aber auf 48h ab jetzt begrenzen
        max_h = min(max(pv_len, hl_len, 72), 72)

        # ── SOC-Stunden-Prognose ───────────────────────────────────────
        # SOC-Forecast:
        #   - 00:00 bis aktuelle volle Stunde: bat_kwh (Ist-Wert) als Platzhalter
        #     → wird im Dashboard durch tatsächlichen SOC-Verlauf überlagert
        #   - Aktuelle volle Stunde bis +48 h: Prognose
        #   - SOC kann nicht unter cutoff_kwh fallen (Entladeschluss)

        # cutoff_kwh vorab berechnen – wird im SOC-Loop als untere Grenze benötigt
        cutoff_kwh_sim = self.cutoff_pct_raw / 100.0 * self.bat_max_kwh

        now_ts       = now_local.timestamp()
        now_floor    = now_local.replace(minute=0, second=0, microsecond=0)
        now_floor_ts = now_floor.timestamp()

        # Anteil der aktuellen Stunde die noch verbleibt (für anteilige Berechnung)
        next_hour_ts       = now_floor_ts + 3600.0
        remaining_fraction = (next_hour_ts - now_ts) / 3600.0

        # Index der aktuellen Stunde in pv_hours/hl_hours (für Restlaufzeit-Simulation)
        midnight_ts = now_local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        now_floor_h = int((now_floor_ts - midnight_ts) / 3600)

        soc = self.bat_kwh
        out: list[dict] = []

        for i in range(max_h):
            if i < pv_len:
                raw_ts = pv_hours[i].get("period_start", "")
            elif i < hl_len:
                raw_ts = hl_hours[i].get("period_start", "")
            else:
                raw_ts = (now_local + timedelta(hours=i)).replace(
                    minute=0, second=0, microsecond=0
                ).isoformat()

            if not isinstance(raw_ts, str):
                try:
                    raw_ts = raw_ts.isoformat()
                except Exception:
                    raw_ts = str(raw_ts)

            try:
                slot_dt = datetime.fromisoformat(raw_ts)
                slot_ts = slot_dt.timestamp()
            except Exception:
                slot_ts = now_floor_ts + i * 3600

            pv_i  = float(pv_hours[i].get("pv_estimate", 0)) if i < pv_len else 0.0
            hl_i  = float(hl_hours[i].get("load_estimate", 0)) if i < hl_len else 0.0
            hl_i += self.force_kwh

            if slot_ts < now_floor_ts:
                # ── Vergangenheit: eingefrorenen Wert wiederverwenden ──
                # Einmal gespeicherte Werte werden nie überschrieben,
                # damit sich vergangene Slots bei Neuberechnung nicht ändern.
                frozen = next(
                    (s for s in self._frozen_past_slots
                     if s["period_start"] == raw_ts),
                    None
                )
                if frozen:
                    out.append(frozen)
                    soc = frozen["soc_kwh"]
                else:
                    # Erster Aufruf für diesen Slot: aktuellen bat_kwh einfrieren
                    entry = {
                        "period_start": raw_ts,
                        "soc_kwh": round(self.bat_kwh, 3),
                        "soc_pct": round(self.bat_kwh / self.bat_max_kwh * 100.0, 1)
                                   if self.bat_max_kwh > 0 else 0.0,
                        "is_forecast": False,
                    }
                    self._frozen_past_slots.append(entry)
                    self._save_cache(_CACHE_SOC, self._frozen_past_slots)
                    out.append(entry)
                    soc = entry["soc_kwh"]

            elif slot_ts == now_floor_ts:
                # Aktuelle volle Stunde: Ist-Wert, kein Einfrieren (ändert sich jede Minute)
                entry = {
                    "period_start": raw_ts,
                    "soc_kwh": round(self.bat_kwh, 3),
                    "soc_pct": round(self.bat_kwh / self.bat_max_kwh * 100.0, 1)
                               if self.bat_max_kwh > 0 else 0.0,
                    "is_forecast": False,
                }
                out.append(entry)
                soc = self.bat_kwh + (pv_i - hl_i) * remaining_fraction
                soc = max(cutoff_kwh_sim, min(soc, self.bat_max_kwh))

            else:
                # Zukunft: Prognose – SOC kann nicht unter Entladeschluss fallen
                soc = soc + (pv_i - hl_i)
                soc = max(cutoff_kwh_sim, min(soc, self.bat_max_kwh))
                soc_pct = round(soc / self.bat_max_kwh * 100.0, 1) if self.bat_max_kwh > 0 else 0.0
                out.append({
                    "period_start": raw_ts,
                    "soc_kwh": round(soc, 3),
                    "soc_pct": soc_pct,
                    "is_forecast": True,
                })

        self.soc_forecast = out
        self.soc_slots_processed = len(out)

        # ── Restlaufzeit berechnen ─────────────────────────────────────
        # Puffer: cutoff + 2% als Frühwarnschwelle, damit Restlaufzeit
        # nicht erst im letzten Moment erkannt wird.
        # Hintergrund: Die Simulation clampt soc_kwh auf cutoff_kwh (Zeile 719/724),
        # daher kann entry["soc_kwh"] == cutoff_kwh mehrere Stunden lang gelten.
        # Wir verwenden eine SEPARATE unkontrollierte Simulation (kein Clamping),
        # um den echten ersten Durchgangspunkt durch die Schwelle zu finden.

        # Puffer aus Konfiguration lesen (Einstellungen → Sensoren)
        RUNTIME_BUFFER_PCT = float(self.cfg.get(CONF_RUNTIME_BUFFER_PCT, DEFAULT_RUNTIME_BUFFER_PCT))
        cutoff_kwh = cutoff_kwh_sim
        self.cutoff_kwh = cutoff_kwh
        runtime_threshold_kwh = cutoff_kwh + (RUNTIME_BUFFER_PCT / 100.0 * self.bat_max_kwh)

        runtime_found = False
        self.restlaufzeit_min = MAX_RUNTIME_MIN
        self.battery_empty_at = False

        # ── FIX: Sofortprüfung – Akku bereits am/unter Schwelle ──────
        # Wenn die nutzbare Restkapazität (bat_rest_kwh) unter einem
        # Minimum liegt, ist der Akku faktisch leer – der Inverter
        # entlädt nicht mehr. Schwelle: 50 Wh (0.05 kWh).
        # Verhindert sowohl die 48h-Anzeige als auch unrealistische
        # Restminuten wenn der SOC knapp über dem Cutoff liegt.
        MIN_USABLE_KWH = 0.05
        if self.bat_rest_kwh < MIN_USABLE_KWH:
            self.restlaufzeit_min = 0
            self.battery_empty_at = dt_util.now().strftime("%Y-%m-%d %H:%M")
            runtime_found = True
            _LOGGER.debug(
                "Nutzbare Restkapazität unter Minimum (%.3f kWh < %.3f kWh) → Restlaufzeit = 0",
                self.bat_rest_kwh, MIN_USABLE_KWH,
            )

        # Unkontrollierte Simulation: SOC darf unter Cutoff fallen,
        # damit der erste Durchgang durch die Schwelle korrekt erkannt wird.
        # Startwert: aktueller SOC + anteiliger Rest der aktuellen Stunde
        # Index-Basis: pv_hours[i] und hl_hours[i] sind tagesbasiert (i=0 → 00:00 heute)
        # → now_floor_h = Stunden seit Mitternacht = korrekter Index für aktuelle Stunde
        if not runtime_found:
            soc_rt = self.bat_kwh
            if now_floor_h < min(pv_len, hl_len):
                pv_current = float(pv_hours[now_floor_h].get("pv_estimate", 0))
                hl_current = float(hl_hours[now_floor_h].get("load_estimate", 0))
                soc_rt = soc_rt + (pv_current - hl_current - self.force_kwh) * remaining_fraction

            for entry in out:
                if not entry.get("is_forecast", False):
                    continue
                try:
                    slot_ts = datetime.fromisoformat(entry["period_start"]).timestamp()
                    # Absoluter Tages-Index: Stunden seit Mitternacht heute
                    # (identisch mit der Indexierung von pv_hours/hl_hours)
                    slot_i = round((slot_ts - midnight_ts) / 3600)
                except Exception:
                    continue

                pv_rt = float(pv_hours[slot_i].get("pv_estimate", 0)) if slot_i < pv_len else 0.0
                hl_rt = float(hl_hours[slot_i].get("load_estimate", 0)) if slot_i < hl_len else 0.0
                hl_rt += self.force_kwh
                soc_rt = soc_rt + (pv_rt - hl_rt)
                # Kein Clamping – SOC kann unter Cutoff fallen

                if soc_rt <= runtime_threshold_kwh and slot_ts > now_ts:
                    self.restlaufzeit_min = int((slot_ts - now_ts) / 60)
                    empty_dt = datetime.fromisoformat(entry["period_start"])
                    self.battery_empty_at = empty_dt.strftime("%Y-%m-%d %H:%M")
                    runtime_found = True
                    break

        if not runtime_found:
            self.restlaufzeit_min = MAX_RUNTIME_MIN
            self.battery_empty_at = False

        # ── Akku-Only-Restlaufzeit (ohne PV) ──────────────────────────
        # Berechnet wie lange der Akku allein die Hauslast versorgen kann.
        # Verwendet die aktuelle Hauslast (Durchschnitt der nächsten Stunden)
        # als Basis. Gibt 0 zurück wenn der Akku am Cutoff ist.
        hauslast_current_kw = 0.0
        # Durchschnitt der nächsten 3 Forecast-Stunden für stabileren Wert
        future_hl = [
            float(hl_hours[h].get("load_estimate", 0))
            for h in range(now_floor_h, min(now_floor_h + 3, hl_len))
            if h < hl_len
        ]
        if future_hl:
            hauslast_current_kw = sum(future_hl) / len(future_hl)

        if hauslast_current_kw > 0.001 and self.bat_rest_kwh > 0.001:
            bat_only_h = self.bat_rest_kwh / hauslast_current_kw
            self.bat_only_runtime_min = min(int(bat_only_h * 60), MAX_RUNTIME_MIN)
        else:
            self.bat_only_runtime_min = 0

        # MAE: mittlere absolute Abweichung Prognose vs. Ist-Verbrauch heute
        try:
            hl_state = self.hass.states.get("sensor.hlf_hauslast_stundlich")
            hourly_history = (
                hl_state.attributes.get("hourly_history", [])
                if hl_state else []
            )
            mae_diffs = []
            for hist in hourly_history:
                hist_hour = datetime.fromisoformat(hist["hour"]).hour
                for fc in self.forecast_heute:
                    fc_hour = datetime.fromisoformat(fc["period_start"]).hour
                    if hist_hour == fc_hour:
                        mae_diffs.append(abs(hist["kwh"] - fc["load_estimate"]))
                        break
            self.forecast_mae_today = round(sum(mae_diffs) / len(mae_diffs), 3) if mae_diffs else 0.0
        except Exception as exc:
            _LOGGER.debug("MAE-Berechnung fehlgeschlagen: %s", exc)
            self.forecast_mae_today = 0.0

        self._has_valid_data = True


# ── Sensor-Klassen ─────────────────────────────────────────────────────────────

class _HauslastBaseSensor(SensorEntity):
    _attr_has_entity_name = False

    def __init__(self, coordinator: HauslastCoordinator, entry: ConfigEntry):
        self._coordinator = coordinator
        self._entry = entry

    @property
    def available(self) -> bool:
        """Sensor ist erst verfügbar wenn der Coordinator mindestens einmal
        erfolgreich durchgerechnet hat. Verhindert, dass 0-Startwerte nach
        einem HA-Neustart im Recorder aufgezeichnet werden."""
        return self._coordinator._has_valid_data

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "House Load Forecast",
            "manufacturer": "Custom",
            "model": "House Load Forecast & PV Battery Runtime",
        }

    async def async_added_to_hass(self):
        if hasattr(self, "_translation_key_for_name"):
            self._attr_name = _get_sensor_name(self.hass, self._translation_key_for_name)
        self.async_write_ha_state()


class HauslastFallbackSensor(_HauslastBaseSensor):
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, typ: str, entry):
        super().__init__(coordinator, entry)
        self._typ = typ
        _typ_en = "weekday" if typ == "wochentag" else "weekend"
        self._attr_unique_id = f"{DOMAIN}_fallback_{_typ_en}_{entry.entry_id}"
        self._attr_translation_key = f"fallback_{_typ_en}"
        self._translation_key_for_name = f"fallback_{_typ_en}"
        self.entity_id = f"sensor.hlf_fallback_{_typ_en}"
        self._attr_icon = "mdi:home-lightning-bolt"

    @property
    def state(self):
        return f"Fallback {'Wochentag' if self._typ == 'wochentag' else 'Wochenende'}"

    @property
    def extra_state_attributes(self):
        profile = self._coordinator.profile_wt if self._typ == "wochentag" else self._coordinator.profile_we
        return {"stunden": profile}

    @property
    def should_poll(self):
        return False


class HauslastPrognoseHeuteSensor(_HauslastBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_forecast_today_{entry.entry_id}"
        self._attr_translation_key = "forecast_today"
        self._translation_key_for_name = "forecast_today"
        self.entity_id = "sensor.hlf_forecast_today"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:home-lightning-bolt"

    @property
    def native_value(self):
        return round(sum(e["load_estimate"] for e in self._coordinator.forecast_heute), 3)

    @property
    def extra_state_attributes(self):
        c = self._coordinator
        now_hour = dt_util.now().hour
        rest = sum(
            e["load_estimate"]
            for h, e in enumerate(c.forecast_heute)
            if h >= now_hour
        )
        d  = c.data_days
        hw = c.history_weeks_used
        if d < MIN_DATA_DAYS:
            basis = "Fallback (manuell)"
        elif hw == 0:
            basis = f"Historisch (gesamte Datenbasis, {d} Tage)"
        else:
            basis = f"Historisch (letzte {hw} Wochen)"

        today_wd = dt_util.now().weekday()
        today_name = WEEKDAY_NAMES[today_wd].capitalize()
        return {
            "data_days": d,
            "history_weeks": hw if hw > 0 else "unbegrenzt",
            "daten_basis": basis,
            "wochentag": today_name,
            "profil_quelle_heute": c.profile_sources[today_wd],
            "forecast_kwh_rest": round(rest, 3),
            # FIX: forecast enthält jetzt alle 24 h ab 00:00
            "forecast": c.forecast_heute,
            "profile_montag":     c.profiles[0],
            "profile_dienstag":   c.profiles[1],
            "profile_mittwoch":   c.profiles[2],
            "profile_donnerstag": c.profiles[3],
            "profile_freitag":    c.profiles[4],
            "profile_samstag":    c.profiles[5],
            "profile_sonntag":    c.profiles[6],
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
        }

    @property
    def should_poll(self):
        return False


class HauslastPrognoseMorgenSensor(_HauslastBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_forecast_tomorrow_{entry.entry_id}"
        self._attr_translation_key = "forecast_tomorrow"
        self._translation_key_for_name = "forecast_tomorrow"
        self.entity_id = "sensor.hlf_forecast_tomorrow"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:home-lightning-bolt-outline"

    @property
    def native_value(self):
        return round(sum(e["load_estimate"] for e in self._coordinator.forecast_morgen), 3)

    @property
    def extra_state_attributes(self):
        c = self._coordinator
        d  = c.data_days
        hw = c.history_weeks_used
        if d < MIN_DATA_DAYS:
            basis = "Fallback (manuell)"
        elif hw == 0:
            basis = f"Historisch (gesamte Datenbasis, {d} Tage)"
        else:
            basis = f"Historisch (letzte {hw} Wochen)"

        tomorrow_wd = (dt_util.now().weekday() + 1) % 7
        tomorrow_name = WEEKDAY_NAMES[tomorrow_wd].capitalize()
        total = sum(e["load_estimate"] for e in c.forecast_morgen)
        return {
            "data_days": d,
            "history_weeks": hw if hw > 0 else "unbegrenzt",
            "daten_basis": basis,
            "wochentag": tomorrow_name,
            "profil_quelle_morgen": c.profile_sources[tomorrow_wd],
            "forecast_kwh_morgen": round(total, 3),
            "forecast": c.forecast_morgen,
            "profile_montag":     c.profiles[0],
            "profile_dienstag":   c.profiles[1],
            "profile_mittwoch":   c.profiles[2],
            "profile_donnerstag": c.profiles[3],
            "profile_freitag":    c.profiles[4],
            "profile_samstag":    c.profiles[5],
            "profile_sonntag":    c.profiles[6],
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
        }

    @property
    def should_poll(self):
        return False



class HauslastPrognoseUebermorgenSensor(_HauslastBaseSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_forecast_day_after_tomorrow_{entry.entry_id}"
        self._attr_translation_key = "forecast_day_after_tomorrow"
        self._translation_key_for_name = "forecast_day_after_tomorrow"
        self.entity_id = "sensor.hlf_forecast_day_after_tomorrow"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:home-lightning-bolt-outline"

    @property
    def native_value(self):
        return round(sum(e["load_estimate"] for e in self._coordinator.forecast_uebermorgen), 3)

    @property
    def extra_state_attributes(self):
        c = self._coordinator
        d  = c.data_days
        hw = c.history_weeks_used
        if d < MIN_DATA_DAYS:
            basis = "Fallback (manuell)"
        elif hw == 0:
            basis = f"Historisch (gesamte Datenbasis, {d} Tage)"
        else:
            basis = f"Historisch (letzte {hw} Wochen)"

        day_after_wd = (dt_util.now().weekday() + 2) % 7
        day_after_name = WEEKDAY_NAMES[day_after_wd].capitalize()
        total = sum(e["load_estimate"] for e in c.forecast_uebermorgen)
        return {
            "data_days": d,
            "history_weeks": hw if hw > 0 else "unbegrenzt",
            "daten_basis": basis,
            "wochentag": day_after_name,
            "profil_quelle_uebermorgen": c.profile_sources[day_after_wd],
            "forecast_kwh_uebermorgen": round(total, 3),
            "forecast": c.forecast_uebermorgen,
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
        }

    @property
    def should_poll(self):
        return False

# ── ForecastCurrentHourSensor ─────────────────────────────────────────────────
# NEU v2.1.2: Gibt den prognostizierten Verbrauch (kWh) der aktuellen Stunde zurück.

class ForecastCurrentHourSensor(_HauslastBaseSensor):
    """Hauslast-Prognose für die aktuelle Stunde (kWh).

    Liest den load_estimate der aktuellen vollen Stunde aus forecast_heute.
    entity_id: sensor.hlf_forecast_current_hour
    """

    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = None
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-clock"
    _attr_should_poll = False

    def __init__(self, coordinator: HauslastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_forecast_current_hour_{entry.entry_id}"
        self._attr_translation_key = "forecast_current_hour"
        self._translation_key_for_name = "forecast_current_hour"
        self.entity_id = "sensor.hlf_forecast_current_hour"

    @property
    def native_value(self) -> float | None:
        now_hour = dt_util.now().hour
        for h, entry in enumerate(self._coordinator.forecast_heute):
            if h == now_hour:
                return round(entry["load_estimate"], 3)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        now_hour = dt_util.now().hour
        load_w = None
        for h, entry in enumerate(self._coordinator.forecast_heute):
            if h == now_hour:
                load_w = round(entry["load_estimate"] * 1000, 1)
                break
        return {
            "hour": now_hour,
            "load_estimate_w": load_w,
        }


# ── ForecastNextHourSensor ───────────────────────────────────────────────────
# NEU v2.1.2: Gibt den prognostizierten Verbrauch (kWh) der nächsten Stunde zurück.

class ForecastNextHourSensor(_HauslastBaseSensor):
    """Hauslast-Prognose für die nächste Stunde (kWh).

    Liest den load_estimate der nächsten vollen Stunde:
    - Stunde 0–22: aus forecast_heute
    - Stunde 23: aus forecast_morgen (Stunde 0)
    entity_id: sensor.hlf_forecast_next_hour
    """

    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = None
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-clock-outline"
    _attr_should_poll = False

    def __init__(self, coordinator: HauslastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_forecast_next_hour_{entry.entry_id}"
        self._attr_translation_key = "forecast_next_hour"
        self._translation_key_for_name = "forecast_next_hour"
        self.entity_id = "sensor.hlf_forecast_next_hour"

    @property
    def native_value(self) -> float | None:
        now_hour = dt_util.now().hour
        next_hour = now_hour + 1
        if next_hour < 24:
            for h, entry in enumerate(self._coordinator.forecast_heute):
                if h == next_hour:
                    return round(entry["load_estimate"], 3)
        else:
            # 23:xx → nächste Stunde ist 00:00 morgen
            if self._coordinator.forecast_morgen:
                return round(self._coordinator.forecast_morgen[0]["load_estimate"], 3)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        now_hour = dt_util.now().hour
        next_hour = (now_hour + 1) % 24
        load_w = None
        if now_hour < 23:
            for h, entry in enumerate(self._coordinator.forecast_heute):
                if h == next_hour:
                    load_w = round(entry["load_estimate"] * 1000, 1)
                    break
        else:
            if self._coordinator.forecast_morgen:
                load_w = round(self._coordinator.forecast_morgen[0]["load_estimate"] * 1000, 1)
        return {
            "hour": next_hour,
            "is_tomorrow": now_hour == 23,
            "load_estimate_w": load_w,
        }


class AkkuRestlaufzeitSensor(_HauslastBaseSensor, RestoreEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_battery_runtime_{entry.entry_id}"
        self._attr_translation_key = "battery_runtime"
        self._translation_key_for_name = "battery_runtime"
        self.entity_id = "sensor.hlf_battery_runtime"
        self._attr_native_unit_of_measurement = "min"
        self._attr_icon = "mdi:battery-clock"
        self._restored_value: int | None = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable", "None", ""):
            try:
                self._restored_value = int(float(last_state.state))
            except (ValueError, TypeError):
                self._restored_value = None
        self.async_write_ha_state()

    @property
    def native_value(self):
        if not self._coordinator._has_valid_data:
            return self._restored_value
        return self._coordinator.restlaufzeit_min

    @property
    def extra_state_attributes(self):
        c = self._coordinator
        # battery_empty_at: False wenn Akku reicht (MAX_RUNTIME), sonst Zeitstempel-String
        empty_at = c.battery_empty_at
        return {
            "calculation_timestamp": c.calculation_timestamp,
            "data_days": c.data_days,
            "history_weeks": c.history_weeks_used if c.history_weeks_used > 0 else "unbegrenzt",
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
            "bat_soc_pct": round(c.soc_pct_raw, 1),
            # NEU: Zeitpunkt Akku leer (False = reicht durch)
            "battery_empty_at": empty_at,
            # Akku-Only-Restlaufzeit ohne PV (Minuten)
            "bat_only_runtime_min": c.bat_only_runtime_min,
            "diag_cutoff_kwh": round(c.cutoff_kwh, 3),
            "diag_bat_kapazitaet_kwh": round(c.bat_capacity_raw, 3),
            "diag_soc_pct": round(c.soc_pct_raw, 1),
            "diag_cutoff_pct": round(c.cutoff_pct_raw, 1),
            "diag_nutzbar_pct": round(c.usable_pct, 1),
            "diag_force_export_aktiv": c.force_on,
            "diag_force_export_kwh": round(c.force_kwh, 3),
            "diag_profil_quellen": {
                WEEKDAY_NAMES[i].capitalize(): c.profile_sources[i] for i in range(7)
            },
            "diag_pv_stunden_heute": c.pv_hours_today_count,
            "diag_pv_stunden_morgen": c.pv_hours_morgen_count,
            "diag_pv_stunden_uebermorgen": c.pv_hours_day_after_count,
            "diag_hauslast_slots_heute": c.hauslast_slots_heute,
            "diag_hauslast_slots_morgen": c.hauslast_slots_morgen,
            "diag_hauslast_slots_uebermorgen": c.hauslast_slots_uebermorgen,
            "diag_soc_slots_verarbeitet": c.soc_slots_processed,
            # soc_hourly_forecast enthält soc_kwh, soc_pct und is_forecast
            "soc_hourly_forecast": c.soc_forecast,
            # soc_kwh_cutoff: verbleibende nutzbare kWh pro Stunde (soc_kwh - cutoff_kwh)
            # entspricht dem Wert von sensor.hlf_diag_bat_rest_kwh, aber stündlich aufgelöst
            "soc_kwh_cutoff": [
                {
                    "period_start": e["period_start"],
                    "kwh": round(max(e["soc_kwh"] - c.cutoff_kwh, 0.0), 3),
                    "is_forecast": e.get("is_forecast", False),
                }
                for e in c.soc_forecast
            ],
        }

    @property
    def should_poll(self):
        return False


class DiagnosticSensor(_HauslastBaseSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, coordinator, entry, field: str, name: str,
                 unit: str | None, device_class, icon: str):
        super().__init__(coordinator, entry)
        self._field = field
        self._attr_unique_id = f"{DOMAIN}_diag_{field}_{entry.entry_id}"
        self._attr_translation_key = f"diag_{field}"
        self._translation_key_for_name = f"diag_{field}"
        self.entity_id = f"sensor.hlf_diag_{field}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def native_value(self):
        val = getattr(self._coordinator, self._field, None)
        if isinstance(val, float):
            return round(val, 3)
        return val


# ── HauslastStundlichSensor ────────────────────────────────────────────────────
# NEU v1.1.2: Verbrauchszähler – wird aus dem konfigurierten Leistungssensor (W)
# via Riemann-Integral (links-Rechteck) akkumuliert und vom HA-Recorder
# als stündliche Statistik aufgezeichnet. Ersetzt den externen Recorder-Sensor.

class HauslastStundlichSensor(SensorEntity, RestoreEntity):
    """Abgeleiteter Hauslast-Verbrauchszähler (kWh, stetig steigend).

    Akkumuliert den Leistungssensor (W) der senalse-Integration via
    Riemann-Integral und liefert einen HA-Recorder-kompatiblen
    TOTAL_INCREASING-Sensor für die historische Profilberechnung.
    Die entity_id ist fix: sensor.hlf_hauslast_stundlich.

    Attribute:
        hourly_history: Liste der letzten 48 abgeschlossenen Stunden als
            [{"hour": "2026-06-12T14:00:00+02:00", "kwh": 0.432}, ...]
        current_hour_kwh: Verbrauch der aktuell laufenden Stunde (noch nicht abgeschlossen)
    """

    _attr_has_entity_name = False
    _attr_name = "Hauslast stündlich"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_should_poll = False

    # Anzahl abgeschlossener Stunden die in den Attributen gehalten werden
    HISTORY_HOURS = 24

    # NEU: State wird nicht bei jedem Power-Update (sekündlich) in den Recorder
    # geschrieben, sondern max. einmal pro WRITE_MIN_INTERVAL_S. Die Riemann-
    # Akkumulation (_total_kwh) läuft weiterhin bei jedem Tick, nur der teure
    # async_write_ha_state()-Aufruf wird gedrosselt. Verhindert ~46.000
    # Recorder-Zeilen/Tag pro Sensor.
    WRITE_MIN_INTERVAL_S = 60

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hauslast_stundlich_{entry.entry_id}"
        self.entity_id = GENERATED_HAUSLAST_SENSOR_ID
        self._total_kwh: float = 0.0
        self._last_update: datetime | None = None
        self._last_power_w: float | None = None
        # Zählerstand zu Beginn der aktuellen Stunde
        self._hour_start_kwh: float | None = None
        self._hour_start_ts: datetime | None = None
        # Ringpuffer: abgeschlossene Stunden {"hour": iso-str, "kwh": float}
        self._hourly_history: list[dict] = []
        # Zeitpunkt des letzten async_write_ha_state()-Aufrufs (Throttle)
        self._last_write: datetime | None = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "House Load Forecast",
            "manufacturer": "Custom",
            "model": "House Load Forecast & PV Battery Runtime",
        }

    @property
    def native_value(self) -> float:
        """State = Verbrauch der aktuell laufenden Stunde (current_hour_kwh).
        Der absolute Zählerstand ist im Attribut 'total_kwh' abrufbar.
        """
        if self._hour_start_kwh is not None:
            return round(self._total_kwh - self._hour_start_kwh, 4)
        return 0.0

    @property
    def extra_state_attributes(self) -> dict:
        current_hour_kwh = None
        if self._hour_start_kwh is not None:
            current_hour_kwh = round(self._total_kwh - self._hour_start_kwh, 4)
        last_period = self._hourly_history[-1]["kwh"] if self._hourly_history else None
        return {
            "hourly_history": self._hourly_history[-24:],
            "current_hour_kwh": current_hour_kwh,
            "last_period": last_period,
            "total_kwh": round(self._total_kwh, 4),
        }

    async def async_added_to_hass(self) -> None:
        """Letzten gespeicherten Zählerstand wiederherstellen."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable", None):
            try:
                attrs = last_state.attributes or {}
                # total_kwh aus Attribut laden (State = current_hour_kwh, nicht total)
                if "total_kwh" in attrs:
                    self._total_kwh = float(attrs["total_kwh"])
                # Startwert der laufenden Stunde rekonstruieren:
                # hour_start_kwh = total_kwh - current_hour_kwh
                if "current_hour_kwh" in attrs and attrs["current_hour_kwh"] is not None:
                    current_hour_kwh = float(attrs["current_hour_kwh"])
                    self._hour_start_kwh = self._total_kwh - current_hour_kwh
                    now = dt_util.now()
                    self._hour_start_ts = now.replace(minute=0, second=0, microsecond=0)
                # Stunden-History wiederherstellen
                if "hourly_history" in attrs and isinstance(attrs["hourly_history"], list):
                    self._hourly_history = attrs["hourly_history"][-self.HISTORY_HOURS:]
                _LOGGER.debug(
                    "HauslastStundlichSensor: Neustart – total=%.4f kWh, hour_start=%.4f kWh",
                    self._total_kwh, self._hour_start_kwh or 0.0,
                )
            except (ValueError, TypeError) as exc:
                _LOGGER.warning("HauslastStundlichSensor: Restore fehlgeschlagen: %s", exc)
                self._total_kwh = 0.0
        self.async_write_ha_state()

    def _maybe_close_hour(self, now: datetime) -> bool:
        """Prüft ob eine neue Stunde begonnen hat und schließt die alte ab.

        Rückgabe: True, wenn eine Stunde abgeschlossen wurde (dann soll der
        State sofort geschrieben werden, unabhängig vom Write-Throttle).
        """
        if self._hour_start_ts is None:
            # Erste Initialisierung: aktuelle Stunde merken
            self._hour_start_kwh = self._total_kwh
            self._hour_start_ts = now.replace(minute=0, second=0, microsecond=0)
            return False

        current_hour = now.replace(minute=0, second=0, microsecond=0)
        if current_hour > self._hour_start_ts:
            # Neue Stunde → abgeschlossene Stunde in History eintragen
            kwh_this_hour = round(self._total_kwh - self._hour_start_kwh, 4)
            if kwh_this_hour >= 0:
                entry = {
                    "hour": self._hour_start_ts.isoformat(),
                    "kwh": kwh_this_hour,
                }
                self._hourly_history.append(entry)
                # Ringpuffer begrenzen
                if len(self._hourly_history) > self.HISTORY_HOURS:
                    self._hourly_history = self._hourly_history[-self.HISTORY_HOURS:]
                _LOGGER.debug(
                    "HauslastStundlichSensor: Stunde %s abgeschlossen → %.4f kWh",
                    self._hour_start_ts.isoformat(), kwh_this_hour,
                )
            # Neue Stunde starten
            self._hour_start_kwh = self._total_kwh
            self._hour_start_ts = current_hour
            return True
        return False

    @callback
    def handle_power_update(self, hass, power_entity_id: str) -> None:
        """Leistungswert (W) auslesen und Zähler akkumulieren.

        Wird bei jeder Zustandsänderung des Leistungssensors aufgerufen
        (i.d.R. sekündlich). Integriert via Riemann-links-Rechteck:
        ΔkWh = P_alt [W] × Δt [h]. Die Akkumulation läuft bei jedem Aufruf,
        der Recorder-Write wird jedoch gedrosselt (siehe WRITE_MIN_INTERVAL_S),
        um die HA-Datenbank nicht mit Zehntausenden Zeilen/Tag zu fluten.
        """
        now = dt_util.now()

        # Leistung des Vorgänger-Intervalls akkumulieren (Riemann links)
        if self._last_update is not None and self._last_power_w is not None:
            delta_h = (now - self._last_update).total_seconds() / 3600.0
            # Plausibilitätsprüfung: max. 2 Stunden Lücke berücksichtigen
            if 0 < delta_h <= 2.0:
                delta_kwh = self._last_power_w * delta_h / 1000.0
                if delta_kwh > 0:
                    self._total_kwh += delta_kwh
                    _LOGGER.debug(
                        "HauslastStundlichSensor: +%.4f kWh (P=%.1f W, Δt=%.2f h) → Gesamt: %.4f kWh",
                        delta_kwh, self._last_power_w, delta_h, self._total_kwh,
                    )

        # Stundenwechsel prüfen und ggf. abgeschlossene Stunde in History schreiben
        hour_closed = self._maybe_close_hour(now)

        # Neuen Leistungswert merken
        state = hass.states.get(power_entity_id)
        if state and state.state not in ("unknown", "unavailable", ""):
            try:
                power_w = float(state.state)
                self._last_power_w = max(power_w, 0.0)  # negative Werte ignorieren
            except (ValueError, TypeError):
                self._last_power_w = None
        else:
            self._last_power_w = None

        self._last_update = now

        # Write-Throttle: sofort schreiben bei Stundenabschluss oder erstem
        # Update, sonst höchstens alle WRITE_MIN_INTERVAL_S Sekunden.
        due = (
            hour_closed
            or self._last_write is None
            or (now - self._last_write).total_seconds() >= self.WRITE_MIN_INTERVAL_S
        )
        if due:
            self._last_write = now
            self.async_write_ha_state()


# ── HauslastTaeglichSensor ─────────────────────────────────────────────────────
# NEU v1.1.2: Täglicher Verbrauchszähler – wird parallel zum stündlichen Sensor
# aus demselben Leistungssensor akkumuliert. State = Verbrauch des laufenden Tages
# (kWh). TOTAL_INCREASING für den HA-Recorder, tägliche Differenzen im Dashboard.

class HauslastTaeglichSensor(SensorEntity, RestoreEntity):
    """Täglicher Hauslast-Verbrauchszähler (kWh, stetig steigend, TOTAL_INCREASING).

    State = Verbrauch des aktuell laufenden Tages (ab 00:00 Uhr).
    Der absolute Gesamtzähler ist im Attribut 'total_kwh' verfügbar.
    entity_id ist fix: sensor.hlf_hauslast_taglich.
    """

    _attr_has_entity_name = False
    _attr_name = "Hauslast täglich"
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:home-lightning-bolt-outline"
    _attr_should_poll = False

    # NEU: siehe HauslastStundlichSensor.WRITE_MIN_INTERVAL_S – gleiche
    # Drosselung des Recorder-Writes, unabhängige Akkumulation bleibt exakt.
    WRITE_MIN_INTERVAL_S = 60

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hauslast_taeglich_{entry.entry_id}"
        self.entity_id = GENERATED_HAUSLAST_DAILY_ID
        self._total_kwh: float = 0.0
        self._last_update: datetime | None = None
        self._last_power_w: float | None = None
        # Zählerstand zu Beginn des aktuellen Tages
        self._day_start_kwh: float | None = None
        self._day_start_ts: datetime | None = None
        # Verlauf der letzten 14 abgeschlossenen Tage
        self._daily_history: list[dict] = []
        # Zeitpunkt des letzten async_write_ha_state()-Aufrufs (Throttle)
        self._last_write: datetime | None = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "House Load Forecast",
            "manufacturer": "Custom",
            "model": "House Load Forecast & PV Battery Runtime",
        }

    @property
    def native_value(self) -> float:
        """State = Verbrauch des aktuell laufenden Tages (ab 00:00 Uhr)."""
        if self._day_start_kwh is not None:
            return round(self._total_kwh - self._day_start_kwh, 4)
        return 0.0

    @property
    def extra_state_attributes(self) -> dict:
        today_kwh = None
        if self._day_start_kwh is not None:
            today_kwh = round(self._total_kwh - self._day_start_kwh, 4)
        yesterday_kwh = self._daily_history[-1]["kwh"] if self._daily_history else None
        return {
            "daily_history": self._daily_history[-14:],
            "today_kwh": today_kwh,
            "yesterday_kwh": yesterday_kwh,
            "total_kwh": round(self._total_kwh, 4),
        }

    async def async_added_to_hass(self) -> None:
        """Letzten gespeicherten Zählerstand wiederherstellen."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable", None):
            try:
                attrs = last_state.attributes or {}
                # total_kwh aus Attribut laden (State = today_kwh, nicht total)
                if "total_kwh" in attrs:
                    self._total_kwh = float(attrs["total_kwh"])
                # Startwert des laufenden Tages rekonstruieren:
                # day_start_kwh = total_kwh - today_kwh
                if "today_kwh" in attrs and attrs["today_kwh"] is not None:
                    today_kwh = float(attrs["today_kwh"])
                    self._day_start_kwh = self._total_kwh - today_kwh
                    now = dt_util.now()
                    self._day_start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
                # Tages-History wiederherstellen
                if "daily_history" in attrs and isinstance(attrs["daily_history"], list):
                    self._daily_history = attrs["daily_history"][-14:]
                _LOGGER.debug(
                    "HauslastTaeglichSensor: Neustart – total=%.4f kWh, day_start=%.4f kWh",
                    self._total_kwh, self._day_start_kwh or 0.0,
                )
            except (ValueError, TypeError) as exc:
                _LOGGER.warning("HauslastTaeglichSensor: Restore fehlgeschlagen: %s", exc)
                self._total_kwh = 0.0
        self.async_write_ha_state()

    def _maybe_close_day(self, now: datetime) -> bool:
        """Prüft ob ein neuer Tag begonnen hat und schließt den alten ab.

        Rückgabe: True, wenn ein Tag abgeschlossen wurde (dann soll der
        State sofort geschrieben werden, unabhängig vom Write-Throttle).
        """
        if self._day_start_ts is None:
            self._day_start_kwh = self._total_kwh
            self._day_start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return False

        current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if current_day > self._day_start_ts:
            kwh_today = round(self._total_kwh - self._day_start_kwh, 4)
            if kwh_today >= 0:
                self._daily_history.append({
                    "day": self._day_start_ts.strftime("%Y-%m-%d"),
                    "kwh": kwh_today,
                })
                if len(self._daily_history) > 14:
                    self._daily_history = self._daily_history[-14:]
                _LOGGER.debug(
                    "HauslastTaeglichSensor: Tag %s abgeschlossen → %.4f kWh",
                    self._day_start_ts.strftime("%Y-%m-%d"), kwh_today,
                )
            self._day_start_kwh = self._total_kwh
            self._day_start_ts = current_day
            return True
        return False

    @callback
    def handle_power_update(self, hass, power_entity_id: str) -> None:
        """Leistungswert (W) auslesen und Tageszähler akkumulieren (Riemann links).

        Akkumulation läuft bei jedem Aufruf (i.d.R. sekündlich), der
        Recorder-Write wird gedrosselt (WRITE_MIN_INTERVAL_S).
        """
        now = dt_util.now()

        if self._last_update is not None and self._last_power_w is not None:
            delta_h = (now - self._last_update).total_seconds() / 3600.0
            if 0 < delta_h <= 2.0:
                delta_kwh = self._last_power_w * delta_h / 1000.0
                if delta_kwh > 0:
                    self._total_kwh += delta_kwh

        day_closed = self._maybe_close_day(now)

        state = hass.states.get(power_entity_id)
        if state and state.state not in ("unknown", "unavailable", ""):
            try:
                self._last_power_w = max(float(state.state), 0.0)
            except (ValueError, TypeError):
                self._last_power_w = None
        else:
            self._last_power_w = None

        self._last_update = now

        due = (
            day_closed
            or self._last_write is None
            or (now - self._last_write).total_seconds() >= self.WRITE_MIN_INTERVAL_S
        )
        if due:
            self._last_write = now
            self.async_write_ha_state()


# ── SocPrognoseAtMidnightSensor ───────────────────────────────────────────────
# NEU v1.2.0: Diagnosesensor – speichert den prognostizierten SOC-Wert (%)
# für den Slot 00:00 Uhr des aktuellen Tages, wie er zum Zeitpunkt des ersten
# Prognose-Laufs nach Mitternacht berechnet wurde.
# Einmal täglich eingefroren → erscheint in der HA-Statistik für Vergleich.

class SocPrognoseAtMidnightSensor(_HauslastBaseSensor, RestoreEntity):
    """SOC-Tagesprognose, eingefroren um Mitternacht – stündliche Zeitreihe.

    Funktionsweise:
    - Täglich um 00:00 Uhr wird ein Snapshot der nächsten 72 Stunden aus
      soc_forecast eingefroren: {ISO-Stunde → soc_pct}.
    - Bei jedem Coordinator-Update gibt native_value den Snapshot-Wert
      für die *aktuelle* Stunde zurück → stündliche Statistiklinie im Chart.
    - Um Mitternacht (Datumswechsel) wird der Snapshot automatisch erneuert.

    entity_id: sensor.hlf_diag_soc_prognose_midnight
    state_class: MEASUREMENT → geht in HA-Statistik (stündlicher Mittelwert)
    """

    _attr_native_unit_of_measurement = "%"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-clock-outline"
    _attr_should_poll = False

    # Persistente Cache-Datei für den 72h-Snapshot
    _CACHE_PATH = "/config/.storage/houseload_forecast_midnight_snapshot.json"
    # Anzahl Stunden die der Snapshot umfasst
    SNAPSHOT_HOURS = 72

    def __init__(self, coordinator: HauslastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_diag_soc_prognose_midnight_{entry.entry_id}"
        self._attr_translation_key = "diag_soc_prognose_midnight"
        self._translation_key_for_name = "diag_soc_prognose_midnight"
        self.entity_id = "sensor.hlf_diag_soc_prognose_midnight"
        # Snapshot: {ISO-Stunde → soc_pct} für 72 Stunden ab Mitternacht
        self._snapshot: dict[str, float] = {}
        self._snapshot_date: str = ""  # "YYYY-MM-DD" des letzten Snapshot-Tages

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Cache vom Disk laden – überleben HA-Neustart
        await self.hass.async_add_executor_job(self._load_snapshot_from_disk)
        self.async_write_ha_state()

    def _load_snapshot_from_disk(self) -> None:
        """Lädt den 72h-Snapshot aus der JSON-Cache-Datei."""
        try:
            if os.path.exists(self._CACHE_PATH):
                with open(self._CACHE_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                today_str = dt_util.now().strftime("%Y-%m-%d")
                # Snapshot akzeptieren wenn er vom heutigen Tag stammt
                if data.get("date") == today_str:
                    self._snapshot = data.get("snapshot", {})
                    self._snapshot_date = today_str
                    _LOGGER.debug(
                        "SocPrognoseAtMidnightSensor: 72h-Snapshot für %s geladen (%d Slots)",
                        today_str, len(self._snapshot),
                    )
        except Exception as exc:
            _LOGGER.debug("SocPrognoseAtMidnightSensor: Cache laden fehlgeschlagen: %s", exc)

    def _save_snapshot_to_disk(self) -> None:
        """Speichert den 72h-Snapshot in die JSON-Cache-Datei."""
        try:
            os.makedirs(os.path.dirname(self._CACHE_PATH), exist_ok=True)
            with open(self._CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {"date": self._snapshot_date, "snapshot": self._snapshot},
                    f, ensure_ascii=False,
                )
        except Exception as exc:
            _LOGGER.debug("SocPrognoseAtMidnightSensor: Cache speichern fehlgeschlagen: %s", exc)

    def _maybe_take_snapshot(self) -> None:
        """Erstellt einen neuen 72h-Snapshot wenn der Datumswechsel eingetreten ist.

        Bedingung: Das aktuelle Datum (YYYY-MM-DD) unterscheidet sich vom
        gespeicherten _snapshot_date → einmalige Erneuerung um Mitternacht.
        Danach bleibt der Snapshot für den gesamten Tag eingefroren.
        Ist idempotent – kann beliebig oft aufgerufen werden.
        """
        today_str = dt_util.now().strftime("%Y-%m-%d")
        if self._snapshot_date == today_str and self._snapshot:
            return  # Snapshot für heute bereits vorhanden

        # Zeitfenster: von 00:00 heute bis 72h später
        now_local = dt_util.now()
        midnight_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = midnight_today + timedelta(hours=self.SNAPSHOT_HOURS)

        new_snapshot: dict[str, float] = {}
        for slot in self._coordinator.soc_forecast:
            ps = slot.get("period_start", "")
            soc_pct = slot.get("soc_pct")
            if soc_pct is None:
                continue
            try:
                dt_slot = datetime.fromisoformat(ps)
                # Naive Slots als Lokalzeit behandeln
                if dt_slot.tzinfo is None:
                    dt_slot = dt_slot.replace(tzinfo=midnight_today.tzinfo)
            except Exception:
                continue
            if not (midnight_today <= dt_slot < cutoff):
                continue
            # Schlüssel: naive ISO-Stunde (ohne Offset) für Chart-Kompatibilität
            key = dt_slot.replace(minute=0, second=0, microsecond=0,
                                  tzinfo=None).isoformat()
            new_snapshot[key] = round(float(soc_pct), 1)

        if not new_snapshot:
            return  # soc_forecast noch leer – nächsten Coordinator-Lauf abwarten

        self._snapshot = new_snapshot
        self._snapshot_date = today_str
        self.hass.async_add_executor_job(self._save_snapshot_to_disk)
        _LOGGER.debug(
            "SocPrognoseAtMidnightSensor: Neuer 72h-Snapshot für %s (%d Slots, "
            "von %s bis %s)",
            today_str, len(new_snapshot),
            midnight_today.isoformat(), cutoff.isoformat(),
        )

    def _current_hour_key(self) -> str:
        """Gibt den ISO-Schlüssel (naiv, ohne Offset) für die aktuelle volle Stunde zurück."""
        now = dt_util.now()
        return now.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat()

    @property
    def native_value(self) -> float | None:
        self._maybe_take_snapshot()
        return self._snapshot.get(self._current_hour_key())

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "snapshot_datum": self._snapshot_date,
            "snapshot_stunden": len(self._snapshot),
            "snapshot_horizon_h": self.SNAPSHOT_HOURS,
            "snapshot": self._snapshot,  # Alle 72 Stunden-Werte zur Inspektion
            "aktuelle_stunde_key": self._current_hour_key(),
            "hinweis": (
                f"SOC-Prognose eingefroren um Mitternacht für {self.SNAPSHOT_HOURS}h. "
                "native_value = Prognosewert der aktuellen Stunde → "
                "Vergleichslinie im HA-Statistik-Chart."
            ),
        }


# ── SocAktuellStatistikSensor ─────────────────────────────────────────────────
# NEU v1.2.0: Spiegelt den konfigurierten Batterie-SOC-Sensor (%) als eigenen
# MEASUREMENT-Sensor in die HA-Statistik. Ermöglicht Vergleichsdiagramm gegen
# SocPrognoseAtMidnightSensor.

class SocAktuellStatistikSensor(_HauslastBaseSensor):
    """Batterieladezustand aktuell (für Statistik/Vergleich).

    Leitet soc_pct_raw des Coordinators (= konfigurierter SOC-Sensor) weiter –
    als MEASUREMENT-Sensor der Integration, damit er neben
    sensor.hlf_diag_soc_prognose_midnight in der HA-Statistik erscheint.

    entity_id: sensor.hlf_diag_soc_aktuell
    state_class: MEASUREMENT → geht in HA-Statistik
    """

    _attr_native_unit_of_measurement = "%"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-heart-variant"
    _attr_should_poll = False

    def __init__(self, coordinator: HauslastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_diag_soc_aktuell_{entry.entry_id}"
        self._attr_translation_key = "diag_soc_aktuell"
        self._translation_key_for_name = "diag_soc_aktuell"
        self.entity_id = "sensor.hlf_diag_soc_aktuell"

    @property
    def native_value(self) -> float | None:
        soc = self._coordinator.soc_pct_raw
        if soc <= 0 and not self._coordinator._has_valid_data:
            return None
        return round(soc, 1)

    @property
    def extra_state_attributes(self) -> dict:
        c = self._coordinator
        return {
            "quelle": c.cfg.get(CONF_BAT_SOC_SENSOR, ""),
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
            "aktualisiert": c.calculation_timestamp,
        }
