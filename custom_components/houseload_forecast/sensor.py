"""Sensor platform for Hauslast Prognose & Akku Restlaufzeit."""
from __future__ import annotations

import logging
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
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

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
    MIN_DATA_DAYS,
    WEEKDAY_NAMES,
    DEFAULT_FALLBACK_WT,
    DEFAULT_FALLBACK_WE,
    FALLBACK_WT_KEYS,
    FALLBACK_WE_KEYS,
)

_LOGGER = logging.getLogger(__name__)

DB_PATH = "/config/home-assistant_v2.db"

# Python weekday(): 0=Mo, 1=Di, 2=Mi, 3=Do, 4=Fr, 5=Sa, 6=So
# SQLite strftime('%w'): 0=So, 1=Mo, 2=Di, 3=Mi, 4=Do, 5=Fr, 6=Sa
# Mapping SQLite-dow → Python-weekday:
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

    sensors = [
        HauslastFallbackSensor(coordinator, "wochentag", entry),
        HauslastFallbackSensor(coordinator, "wochenende", entry),
        HauslastPrognoseHeuteSensor(coordinator, entry),
        HauslastPrognoseMorgenSensor(coordinator, entry),
        AkkuRestlaufzeitSensor(coordinator, entry),
        DiagnosticSensor(coordinator, entry, "calculation_timestamp",
                         "Last Forecast Update", None, None, "mdi:clock-outline"),
        DiagnosticSensor(coordinator, entry, "data_days",
                         "Data History Days", "d", None, "mdi:database-clock"),
        DiagnosticSensor(coordinator, entry, "soc_pct_raw",
                         "Battery State of Charge", "%", None, "mdi:battery"),
        DiagnosticSensor(coordinator, entry, "bat_max_kwh",
                         "Effective Battery Capacity", "kWh", None, "mdi:battery-high"),
        DiagnosticSensor(coordinator, entry, "bat_kwh",
                         "Usable Capacity", "kWh", None, "mdi:battery-arrow-up"),
        DiagnosticSensor(coordinator, entry, "bat_rest_kwh",
                         "Remaining Capacity to Cutoff", "kWh", None, "mdi:battery-arrow-down-outline"),
        DiagnosticSensor(coordinator, entry, "force_on",
                         "Force Export Active", None, None, "mdi:transmission-tower-export"),
    ]

    async_add_entities(sensors, True)
    coordinator.async_register_entities(sensors)

    watch_entities = [
        cfg.get(CONF_BAT_CAPACITY_SENSOR),
        cfg.get(CONF_BAT_SOC_SENSOR),
        cfg.get(CONF_BAT_CUTOFF_SENSOR),
        cfg.get(CONF_PV_TODAY_SENSOR),
        cfg.get(CONF_PV_TOMORROW_SENSOR),
        cfg.get(CONF_FORCE_EXPORT_BOOLEAN),
        cfg.get(CONF_FORCE_EXPORT_POWER),
        cfg.get(CONF_HAUSLAST_STUNDLICH),
    ]
    watch_entities = [e for e in watch_entities if e]

    @callback
    def _state_changed(event):
        coordinator.async_update_all()

    entry.async_on_unload(
        async_track_state_change_event(hass, watch_entities, _state_changed)
    )


class HauslastCoordinator:
    """Central data coordinator."""

    def __init__(self, hass, cfg, fallback_wt, fallback_we):
        self.hass = hass
        self.cfg = cfg
        self.fallback_wt = fallback_wt  # 24-Werte Fallback Wochentag (allgemein)
        self.fallback_we = fallback_we  # 24-Werte Fallback Wochenende (allgemein)
        self._entities: list = []

        # 7 Tagesprofile (Python weekday 0=Mo … 6=So), je 24 Watt-Werte
        self.profiles: list[list[float]] = [[] for _ in range(7)]
        self.profile_sources: list[str] = [""] * 7

        # Für Rückwärtskompatibilität der Sensor-Attribute
        self.profile_wt: list[float] = []
        self.profile_we: list[float] = []
        self.profile_source_wt: str = ""
        self.profile_source_we: str = ""

        self.forecast_heute: list[dict] = []
        self.forecast_morgen: list[dict] = []
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
        self.hauslast_slots_heute: int = 0
        self.hauslast_slots_morgen: int = 0
        self.soc_slots_processed: int = 0
        self.bat_rest_kwh: float = 0.0
        self.cutoff_kwh: float = 0.0

        # Wird True sobald mindestens eine erfolgreiche Berechnung mit validen
        # Sensor-Werten stattgefunden hat. Solange False bleibt restlaufzeit_min
        # auf None (Restore-Wert des Sensors bleibt erhalten).
        self._has_valid_data: bool = False

    def async_register_entities(self, entities):
        self._entities = entities

    @callback
    def async_update_all(self):
        self.hass.async_create_task(self.async_refresh())

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

        self.calculation_timestamp = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")

        # ── History-Wochen aus Config lesen ───────────────────────────
        # 0 = unbegrenzt, sonst Anzahl Wochen
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
            history_param = "-36500 days"   # ~100 Jahre = "alles"
            history_label = "gesamte Datenbasis"

        # ── Datenbasis ermitteln ──────────────────────────────────────
        hauslast_id = self.cfg.get(CONF_HAUSLAST_STUNDLICH, "sensor.hauslast_stundlich")
        statistic_id = hauslast_id

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
                # Sensortyp aus statistics_meta ermitteln
                cur.execute(
                    "SELECT has_mean, has_sum FROM statistics_meta WHERE statistic_id = ?",
                    (statistic_id,)
                )
                meta_row = cur.fetchone()
                sensor_has_mean = meta_row and meta_row[0] == 1

                if sensor_has_mean:
                    # MEASUREMENT (W): mean-Spalte direkt verwenden
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
                    # TOTAL_INCREASING (kWh): state-Spalte enthält stündlichen Verbrauch
                    raw_sql = """
                        SELECT
                            CAST(strftime('%w', datetime(start_ts,'unixepoch','localtime')) AS INTEGER) AS sqlite_dow,
                            CAST(strftime('%H', datetime(start_ts,'unixepoch','localtime')) AS INTEGER) AS hour,
                            state AS val
                        FROM statistics
                        WHERE metadata_id = (SELECT id FROM statistics_meta WHERE statistic_id = ?)
                          AND start_ts >= strftime('%s', datetime('now', ?))
                          AND state IS NOT NULL AND state > 0
                        ORDER BY start_ts
                    """
                    value_col = "state (kWh→W)"
                    scale = 1000.0

                cur.execute(raw_sql, (statistic_id, history_param))
                all_rows = cur.fetchall()

                # Werte in Buckets je Wochentag (Python-weekday 0–6) und Stunde aufteilen
                # buckets[weekday][hour] = [watt, watt, ...]
                buckets: list[list[list[float]]] = [[[] for _ in range(24)] for _ in range(7)]
                for sqlite_dow, hour, val in all_rows:
                    if val is None or val < 0:
                        continue
                    py_wd = _SQLITE_DOW_TO_PY[int(sqlite_dow)]
                    buckets[py_wd][hour].append(float(val) * scale)

                def iqr_filtered_mean(values: list[float], fallback: float) -> float:
                    """Mittelwert nach IQR-Ausreißerfilter (Faktor 3)."""
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

                # Fallback-Profil je Wochentag bestimmen (WT=Mo–Fr, WE=Sa+So)
                def fallback_for(py_wd: int) -> list[float]:
                    return self.fallback_we if py_wd >= 5 else self.fallback_wt

                # Pro Wochentag Profil berechnen
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
                        _LOGGER.debug(
                            "%s-Profil: %d Stunden aus DB (%s)",
                            day_name, hours_with_data, value_col
                        )
                    else:
                        self.profiles[py_wd] = list(fb)
                        self.profile_sources[py_wd] = (
                            f"Fallback (zu wenige Daten für {day_name}: {hours_with_data} Stunden)"
                        )
                        _LOGGER.warning(
                            "%s-Profil: nur %d Stunden – Fallback",
                            day_name, hours_with_data
                        )

                # Rückwärtskompatibilität: WT = Ø Mo–Fr, WE = Ø Sa+So
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
                # Zu wenige Daten → Fallback für alle 7 Tage
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
                _LOGGER.info(
                    "Hauslast-Profil: nur %d Datentage – Fallback für alle Tage",
                    self.data_days
                )

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

        # Sensoren noch nicht bereit (z.B. direkt nach Neustart)?
        # Prüfe ob die Kernwerte plausibel sind: Kapazität > 0 und SoC > 0
        bat_sensors_ready = (
            self.bat_capacity_raw > 0
            and self.soc_pct_raw > 0
        )
        if not bat_sensors_ready:
            # Abhängige Sensoren noch nicht verfügbar → keine neue Berechnung,
            # restlaufzeit_min bleibt unverändert (Restore-Wert bleibt erhalten)
            _LOGGER.debug(
                "Batterie-Sensoren noch nicht verfügbar (capacity=%.1f, soc=%.1f) – "
                "überspringe Restlaufzeit-Berechnung",
                self.bat_capacity_raw, self.soc_pct_raw
            )
            return

        self.usable_pct  = max(self.soc_pct_raw - self.cutoff_pct_raw, 0.0)
        self.bat_max_kwh = self.bat_capacity_raw
        self.bat_kwh     = self.soc_pct_raw / 100.0 * self.bat_max_kwh
        self.bat_rest_kwh = max(self.usable_pct / 100.0 * self.bat_max_kwh, 0.0)

        # ── Force Export ───────────────────────────────────────────────
        self.force_on = False
        fe_state = self._get_state(self.cfg.get(CONF_FORCE_EXPORT_BOOLEAN))
        if fe_state == "on":
            self.force_on = True
        self.force_kwh = self._get_float(self.cfg.get(CONF_FORCE_EXPORT_POWER)) if self.force_on else 0.0

        # ── Hauslast-Forecast aufbauen ─────────────────────────────────
        now_local  = dt_util.now()
        today_wd   = now_local.weekday()   # 0=Mo … 6=So
        tomorrow_wd = (today_wd + 1) % 7

        def build_forecast(profile: list[float], base_date) -> list[dict]:
            result = []
            for h in range(24):
                dt_slot = base_date.replace(hour=h, minute=0, second=0, microsecond=0)
                result.append({
                    "period_start": dt_slot.isoformat(),
                    "load_estimate": round(profile[h] / 1000.0, 3) if h < len(profile) else 0.0,
                })
            return result

        profile_heute  = self.profiles[today_wd]   if self.profiles[today_wd]   else self.fallback_wt
        profile_morgen = self.profiles[tomorrow_wd] if self.profiles[tomorrow_wd] else self.fallback_wt

        self.forecast_heute = build_forecast(profile_heute, now_local)
        self.forecast_morgen = build_forecast(
            profile_morgen,
            (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        )
        self.hauslast_slots_heute  = len(self.forecast_heute)
        self.hauslast_slots_morgen = len(self.forecast_morgen)

        # ── PV-Forecast aus Solcast-Attributen ────────────────────────
        pv_today_list  = self._get_attr(self.cfg.get(CONF_PV_TODAY_SENSOR),    "detailedHourly", []) or []
        pv_morgen_list = self._get_attr(self.cfg.get(CONF_PV_TOMORROW_SENSOR), "detailedHourly", []) or []
        pv_hours = list(pv_today_list) + list(pv_morgen_list)
        self.pv_hours_today_count  = len(pv_today_list)
        self.pv_hours_morgen_count = len(pv_morgen_list)

        hl_hours = self.forecast_heute + self.forecast_morgen
        pv_len = len(pv_hours)
        hl_len = len(hl_hours)
        max_h = min(max(pv_len, hl_len, 48), 48)

        # ── SOC-Stunden-Prognose ───────────────────────────────────────
        now_ts        = now_local.timestamp()
        now_floor     = now_local.replace(minute=0, second=0, microsecond=0)
        now_floor_ts  = now_floor.timestamp()
        next_hour_ts  = now_floor_ts + 3600.0
        remaining_fraction = (next_hour_ts - now_ts) / 3600.0

        soc = self.bat_kwh
        out: list[dict] = []
        first_future_slot = True

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

            if slot_ts < now_floor_ts:
                continue

            pv_i  = float(pv_hours[i].get("pv_estimate", 0)) if i < pv_len else 0.0
            hl_i  = float(hl_hours[i].get("load_estimate", 0)) if i < hl_len else 0.0
            hl_i += self.force_kwh

            if slot_ts == now_floor_ts:
                out.append({"period_start": raw_ts, "soc_kwh": round(self.bat_kwh, 3)})
                soc = self.bat_kwh + (pv_i - hl_i) * remaining_fraction
                soc = max(0.0, min(soc, self.bat_max_kwh))
            else:
                if first_future_slot:
                    first_future_slot = False
                soc = soc + (pv_i - hl_i)
                soc = max(0.0, min(soc, self.bat_max_kwh))
                out.append({"period_start": raw_ts, "soc_kwh": round(soc, 3)})

        self.soc_forecast = out
        self.soc_slots_processed = len(out)

        # ── Restlaufzeit berechnen ─────────────────────────────────────
        cutoff_kwh = self.cutoff_pct_raw / 100.0 * self.bat_max_kwh
        self.cutoff_kwh = cutoff_kwh
        self.restlaufzeit_min = max_h * 60
        for entry in out:
            try:
                slot_ts = datetime.fromisoformat(entry["period_start"]).timestamp()
            except Exception:
                continue
            if entry["soc_kwh"] <= cutoff_kwh and slot_ts > now_ts:
                self.restlaufzeit_min = int((slot_ts - now_ts) / 60)
                break

        # Berechnung war erfolgreich mit validen Werten
        self._has_valid_data = True


# ── Sensor-Klassen ─────────────────────────────────────────────────────────────

class _HauslastBaseSensor(SensorEntity):
    def __init__(self, coordinator: HauslastCoordinator, entry: ConfigEntry):
        self._coordinator = coordinator
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Hauslast Prognose",
            "manufacturer": "Custom",
            "model": "Hauslast Prognose & Akku Restlaufzeit",
        }

    async def async_added_to_hass(self):
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
        self.entity_id = "sensor.hlf_forecast_today"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = SensorDeviceClass.ENERGY
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
            "forecast": c.forecast_heute,
            # alle 7 Tagesprofile
            "profile_montag":     c.profiles[0],
            "profile_dienstag":   c.profiles[1],
            "profile_mittwoch":   c.profiles[2],
            "profile_donnerstag": c.profiles[3],
            "profile_freitag":    c.profiles[4],
            "profile_samstag":    c.profiles[5],
            "profile_sonntag":    c.profiles[6],
            # Diagnostik
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
        self.entity_id = "sensor.hlf_forecast_tomorrow"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = SensorDeviceClass.ENERGY
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
            # alle 7 Tagesprofile
            "profile_montag":     c.profiles[0],
            "profile_dienstag":   c.profiles[1],
            "profile_mittwoch":   c.profiles[2],
            "profile_donnerstag": c.profiles[3],
            "profile_freitag":    c.profiles[4],
            "profile_samstag":    c.profiles[5],
            "profile_sonntag":    c.profiles[6],
            # Diagnostik
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
        }

    @property
    def should_poll(self):
        return False


class AkkuRestlaufzeitSensor(_HauslastBaseSensor, RestoreEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_battery_runtime_{entry.entry_id}"
        self._attr_translation_key = "battery_runtime"
        self.entity_id = "sensor.hlf_battery_runtime"
        self._attr_native_unit_of_measurement = "min"
        self._attr_icon = "mdi:battery-clock"
        self._restored_value: int | None = None

    async def async_added_to_hass(self):
        """Letzten bekannten Wert beim Start wiederherstellen."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable", "None", ""):
            try:
                self._restored_value = int(float(last_state.state))
                _LOGGER.debug(
                    "Restlaufzeit: letzter Wert wiederhergestellt: %d min",
                    self._restored_value
                )
            except (ValueError, TypeError):
                self._restored_value = None
        self.async_write_ha_state()

    @property
    def native_value(self):
        # Solange noch keine valide Neuberechnung stattgefunden hat,
        # den wiederhergestellten Wert zurückgeben statt 0.
        if not self._coordinator._has_valid_data:
            return self._restored_value
        return self._coordinator.restlaufzeit_min

    @property
    def extra_state_attributes(self):
        c = self._coordinator
        return {
            "calculation_timestamp": c.calculation_timestamp,
            "data_days": c.data_days,
            "history_weeks": c.history_weeks_used if c.history_weeks_used > 0 else "unbegrenzt",
            "bat_kwh": round(c.bat_kwh, 3),
            "bat_max_kwh": round(c.bat_max_kwh, 3),
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
            "diag_hauslast_slots_heute": c.hauslast_slots_heute,
            "diag_hauslast_slots_morgen": c.hauslast_slots_morgen,
            "diag_soc_slots_verarbeitet": c.soc_slots_processed,
            "soc_hourly_forecast": c.soc_forecast,
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
