DOMAIN = "houseload_forecast"

CONF_BAT_CAPACITY_SENSOR = "bat_capacity_sensor"
CONF_BAT_SOC_SENSOR = "bat_soc_sensor"
CONF_BAT_CUTOFF_SENSOR = "bat_cutoff_sensor"
CONF_PV_TODAY_SENSOR = "pv_forecast_today_sensor"
CONF_PV_TOMORROW_SENSOR = "pv_forecast_tomorrow_sensor"
CONF_FORCE_EXPORT_BOOLEAN = "force_export_boolean"
CONF_FORCE_EXPORT_POWER = "force_export_power"
CONF_HAUSLAST_STUNDLICH = "hauslast_stundlich_sensor"
CONF_HISTORY_WEEKS = "history_weeks"  # 1–52 oder 0 = unbegrenzt

DEFAULT_HISTORY_WEEKS = 8   # Voreinstellung: 8 Wochen
MIN_DATA_DAYS = 10          # Mindest-Datenbasis für historische Berechnung

# Wochentagnamen (Python weekday: 0=Mo … 6=So)
WEEKDAY_NAMES = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]

DEFAULT_FALLBACK_WT = [
    435, 420, 420, 420, 420, 420,
    450, 700, 800, 700, 650, 700,
    900, 750, 650, 600, 580, 620,
    700, 680, 600, 500, 500, 500,
]

DEFAULT_FALLBACK_WE = [
    435, 420, 420, 420, 420, 420,
    450, 500, 800, 700, 650, 700,
    750, 700, 650, 600, 580, 620,
    700, 680, 600, 500, 500, 500,
]

FALLBACK_WT_KEYS = [f"fallback_wt_{h:02d}" for h in range(24)]
FALLBACK_WE_KEYS = [f"fallback_we_{h:02d}" for h in range(24)]
