# House Load Forecast & Battery Runtime

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/thokoh74-DE/houseload_forecast.svg)](https://github.com/thokoh74-DE/houseload_forecast/releases)
[![BETA](https://img.shields.io/badge/Status-BETA-red.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🌍 [Deutsch](README.md) | **English**

A Home Assistant custom integration for **hourly house load forecasting** and **battery runtime estimation** for PV systems with battery storage. The forecast is based on actual historical consumption data from the Home Assistant statistics database — differentiated by each individual day of the week.

---

## Feature Overview

- **House Load Forecast (Today & Tomorrow):** Hourly forecast of household consumption in kWh, built from historical data of the last *n* weeks
- **7 Individual Daily Profiles:** Each weekday (Monday to Sunday) gets its own 24-hour profile — no more generic weekday/weekend grouping
- **IQR Outlier Filter:** Measurement artifacts and counter resets are automatically filtered out
- **Configurable Time Range:** From 1 week to unlimited (0 = entire data history)
- **Fallback Profiles:** Manual hourly profiles for weekdays and weekends, used when less than 10 days of data are available
- **Battery Runtime:** Hourly SOC forecast combining PV forecast (Solcast), house load forecast and current battery charge
- **Restore after Restart:** The last known runtime value is preserved after an HA restart until new valid sensor values are available

---

## Requirements

| Requirement | Details |
|---|---|
| Home Assistant | ≥ 2024.1 (recommended: ≥ 2026.3 for icon support) |
| Battery Integration | AlphaESS or similar — must provide capacity (kWh) and SoC (%) as sensors |
| PV Forecast | [Solcast Solar Forecast](https://github.com/BJReplay/ha-solcast-solar) with `detailedHourly` attribute |
| House Load Sensor | Sensor with `state_class: total_increasing` (kWh, hourly) or `measurement` (W) — must be recorded in HA statistics |
| SQLite Database | Standard HA database at `/config/home-assistant_v2.db` |

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. **Integrations** → Three-dot menu top right → **Custom repositories**
3. Enter URL: `https://github.com/thokoh74-DE/houseload_forecast`
4. Category: **Integration** → **Add**
5. The integration **"Hauslast Prognose & Akku Restlaufzeit"** now appears in the HACS list
6. Click **Download** → Restart Home Assistant

### Manual

1. Download the `custom_components/houseload_forecast/` folder from the [latest release](https://github.com/thokoh74-DE/houseload_forecast/releases)
2. Copy to `config/custom_components/houseload_forecast/`
3. Restart Home Assistant

---

## Setup

1. **Settings → Devices & Services → Add Integration**
2. Search for **"Hauslast Prognose"**
3. **Step 1 – Configure sensors:**

| Field | Description |
|---|---|
| Effective battery capacity | Sensor providing usable battery capacity in kWh |
| Battery state of charge (SoC) | Sensor for current charge level in % |
| Discharge cutoff / reserve | Sensor for minimum SoC in % (e.g. `10` for 10% reserve) |
| PV forecast today | Solcast sensor with `detailedHourly` attribute for today |
| PV forecast tomorrow | Solcast sensor with `detailedHourly` attribute for tomorrow |
| PV forecast day after tomorrow | Optional: Solcast sensor for the day after tomorrow — required for a true 48h forecast from now |
| Force export active | Optional: `input_boolean` for force export mode |
| Force export power | Optional: `number` entity with export power in kW |
| House load hourly | Hourly consumption sensor recorded in HA statistics |
| History period | Number of weeks for historical calculation (0 = all data) |

4. **Step 2 – Fallback profiles:** Manual hourly profiles in watts for weekdays (Mon–Fri) and weekends (Sat+Sun) — automatically replaced by historical data once ≥ 10 days are available

---

## Adjusting Settings

Via **Settings → Devices & Services → Hauslast Prognose → Configure**:

- **Edit sensors** – Change sensors and history period (without losing fallback profiles)
- **Edit fallback profiles** – Adjust hourly values (without losing sensor configuration)

---

## Generated Sensors

### Main Sensors

| Sensor | Unit | Description |
|---|---|---|
| `sensor.hlf_forecast_today` | kWh | Daily house load forecast for today (House Load Forecast Today) |
| `sensor.hlf_forecast_tomorrow` | kWh | Daily house load forecast for tomorrow (House Load Forecast Tomorrow) |
| `sensor.hlf_forecast_day_after_tomorrow` | kWh | Daily house load forecast for the day after tomorrow (House Load Forecast Day After Tomorrow) |
| `sensor.hlf_battery_runtime` | min | Remaining time until discharge cutoff (PV Battery Runtime Forecast). The forecast covers **48 hours from now** (today + tomorrow + day after tomorrow). A value of **2880 min means the battery will not run empty within the next 48 hours** based on the current forecast. |

### Key Attributes

**`sensor.hlf_forecast_today` (House Load Forecast Today) / `sensor.hlf_forecast_tomorrow` (House Load Forecast Tomorrow):**

```yaml
forecast:
  - period_start: "2026-05-24T00:00:00+02:00"
    load_estimate: 0.43       # kWh for this hour
  - period_start: "2026-05-24T01:00:00+02:00"
    load_estimate: 0.42
  # ... 24 entries total, always starting from 00:00
profile_montag: [435, 420, ...]   # 24 watt values
profile_dienstag: [...]
# ... all 7 daily profiles
wochentag: "Samstag"
profil_quelle_heute: "Historisch (letzte 8 Wochen, state (kWh→W), IQR-gefiltert)"
daten_basis: "Historisch (letzte 8 Wochen)"
data_days: 56
```

**`sensor.hlf_battery_runtime` (PV Battery Runtime Forecast):**

```yaml
soc_hourly_forecast:
  - period_start: "2026-05-24T00:00:00+02:00"
    soc_kwh: 7.8
    soc_pct: 100.0            # NEW: 100% = bat_max_kwh, 0% = 0 kWh
    is_forecast: false         # NEW: false = actual placeholder (before current hour)
  - period_start: "2026-05-24T09:00:00+02:00"
    soc_kwh: 5.2
    soc_pct: 66.8
    is_forecast: true          # true = forecast value
  # ... up to 48 entries, starting from 00:00 of today
battery_empty_at: "2026-05-25T04:00"   # time battery runs empty – or false if it lasts
bat_kwh: 7.8
bat_max_kwh: 7.78
bat_soc_pct: 100.0
diag_cutoff_pct: 10.0
```

> **Note on `battery_empty_at`:** `false` means the battery is forecast to last through the full 48-h horizon (= 2880 min runtime). Otherwise the timestamp is provided as `YYYY-MM-DD HH:MM`.

### Diagnostic Sensors

All diagnostic sensors appear on the device page under **"Diagnostics"** and are hidden by default:

| Sensor | Description |
|---|---|
| Last forecast update | Timestamp of last calculation |
| Number of data days | How many days of historical data are available |
| Battery state of charge | Current SoC in % |
| Effective battery capacity | Battery capacity in kWh |
| Usable capacity | Currently usable energy in kWh |
| Remaining capacity to cutoff | Remaining energy until discharge cutoff |
| Force export active | Status of force export mode |
| Battery Empty At | Forecast time when battery runs empty (false = lasts through) |

---

## Profile Calculation in Detail

```
Data situation                  Behaviour
─────────────────────────────────────────────────────────
< 10 days data                 → Manual fallback profile
≥ 10 days, MEASUREMENT sensor → AVG(mean) per hour & weekday
≥ 10 days, TOTAL_INC sensor   → AVG(state × 1000) per hour & weekday
Outliers                       → IQR filter (factor 3) before averaging
Hour with too few data points  → Fallback value for that hour
```

The **IQR outlier filter** removes values outside `[Q1 − 3×IQR, Q3 + 3×IQR]` per hour and weekday before calculating the average. This prevents measurement artifacts from HA restarts or counter reset events from being included in the profile.

---

## Dashboard Examples

### Battery Forecast (ApexCharts)

Shows the real battery state of charge from the historian (blue) and the SOC forecast from the current hour onwards (dashed orange) — both in percent on a shared Y-axis.

**Time window:** 00:00 today until now + 24 hours.

- **Battery (actual):** Historical SOC from `sensor.alphaess_soc_battery` (drawn up to "Now" automatically)
- **Forecast SOC:** Projected SOC from the current hour, using only `soc_hourly_forecast` entries with `is_forecast: true`
- **Header:** Current SoC in %, actual SOC in kWh, remaining battery runtime in minutes

![Battery Forecast Dashboard](docs/images/screenshot_akku_prognose.png)

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
graph_span: 48h
header:
  show: true
  show_states: true
  colorize_states: true
  standard_format: true
cache: true
show:
  loading: false
  last_updated: true
now:
  show: true
  label: Now
span:
  start: day
all_series_config:
  show:
    header_color_threshold: true
    legend_value: false
series:
  - entity: sensor.alphaess_soc_battery
    name: Battery (actual)
    transform: return x;
    yaxis_id: battery
    type: area
    color: "#4dabf7"
    extend_to: now
    curve: smooth
    fill_raw: last
    opacity: 0.5
    stroke_width: 2
    float_precision: 1
    group_by:
      func: avg
      duration: 5min
    show:
      legend_value: false
      in_header: false

  - entity: sensor.hlf_battery_runtime
    name: Forecast SOC
    unit: "%"
    yaxis_id: battery
    color: "#ffa94d"
    stroke_width: 2
    stroke_dash: 5
    float_precision: 1
    type: area
    opacity: 0.15
    data_generator: |
      const forecast = entity.attributes.soc_hourly_forecast || [];
      return forecast
        .filter(e => e.is_forecast === true)
        .map(e => [
          new Date(e.period_start).getTime(),
          e.soc_pct
        ]);
    show:
      legend_value: false
      in_header: false
      in_chart: true
    extend_to: false

  - entity: sensor.hlf_diag_soc_pct_raw
    name: Battery
    float_precision: 1
    color: "#4dabf7"
    show:
      in_header: true
      in_chart: false

  - entity: sensor.hlf_diag_bat_kwh
    name: Actual SOC
    unit: kWh
    color: "#00e676"
    float_precision: 1
    show:
      in_header: true
      in_chart: false

  - entity: sensor.hlf_battery_runtime
    name: Runtime
    unit: min
    color: "#ffa94d"
    float_precision: 0
    show:
      in_header: true
      in_chart: false

apex_config:
  chart:
    height: 350px
    stacked: false
  dataLabels:
    enabled: false
  grid:
    padding:
      left: 0
      right: 0
  xaxis:
    type: datetime
    title:
      text: Time
    min: EVAL:new Date().setHours(0,0,0,0)
    max: EVAL:Date.now() + 24 * 60 * 60 * 1000
    labels:
      datetimeFormatter:
        hour: HH:mm
        day: dd.MM
  tooltip:
    x:
      format: dd.MM.yy HH:mm
  fill:
    type: gradient
    gradient:
      shadeIntensity: 1
      opacityFrom: 0.4
      opacityTo: 0.05
      stops:
        - 0
        - 100
yaxis:
  - id: battery
    min: 0
    max: 100
    decimals: 0
    apex_config:
      tickAmount: 8
      title:
        text: Battery in %
      labels:
        formatter: |
          EVAL:function(value) {
            return value.toFixed(0) + '%';
          }
grid_options:
  columns: full
card_mod:
  style: |
    ha-card {
      box-shadow: none;
      border: none;
    }
```

> **Note:** Replace `sensor.alphaess_soc_battery` with your own SOC sensor. The Y-axis max is fixed at 100 % — no adjustment needed.

</details>

---

### House Load Forecast (ApexCharts)

Shows the hourly forecast for today (blue) and tomorrow (orange) as a bar chart, together with the actual consumption (red).

**Time window:** 00:00 today until now + 24 hours.

- **Today (blue):** All 24 hours of today from `sensor.hlf_forecast_today`
- **Tomorrow (orange):** Hours of tomorrow up to now + 24 h from `sensor.hlf_forecast_tomorrow`
- **Actual consumption (red):** Real hourly consumption from `sensor.hauslast_stundlich`

![House Load Forecast Dashboard](docs/images/screenshot_hauslast_prognose.png)

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
graph_span: 48h
header:
  show: true
  show_states: true
  colorize_states: true
cache: true
show:
  loading: true
  last_updated: true
all_series_config:
  show:
    header_color_threshold: true
    legend_value: false
apex_config:
  chart:
    height: 350px
    width: 100%
    stacked: true
  plotOptions:
    bar:
      columnWidth: 70%
  dataLabels:
    enabled: false
  grid:
    padding:
      left: 0
      right: 0
  xaxis:
    title:
      text: Time
    min: EVAL:new Date().setHours(0,0,0,0)
    max: EVAL:Date.now() + 24 * 60 * 60 * 1000
    labels:
      show: true
      tickPlacement: between
      datetimeFormatter:
        hour: HH:mm
        day: dd.MM
  yaxis:
    title:
      text: kWh
    labels:
      show: true
    min: 0
    max: 3
    stepSize: 0.5
    decimalsInFloat: 1
span:
  start: day
now:
  show: true
  label: Now
series:
  - entity: sensor.hlf_forecast_today
    name: Today
    type: column
    color: "#4dabf7"
    unit: kWh
    show:
      in_header: false
      legend_value: false
    data_generator: |
      const forecast = entity.attributes.forecast || [];
      return forecast.map(item => [
        new Date(item.period_start).getTime(),
        item.load_estimate
      ]);
  - entity: sensor.hlf_forecast_today
    name: Forecast Today
    float_precision: 1
    color: "#4dabf7"
    unit: kWh
    transform: return parseFloat(entity.state);
    show:
      in_chart: false
      in_header: true
  - entity: sensor.hlf_forecast_tomorrow
    name: Tomorrow
    type: column
    color: "#ffa94d"
    unit: kWh
    transform: return parseFloat(entity.state);
    show:
      in_header: false
      legend_value: false
    data_generator: |
      const forecast = entity.attributes.forecast || [];
      const cutoff = Date.now() + 24 * 60 * 60 * 1000;
      return forecast
        .map(item => [new Date(item.period_start).getTime(), item.load_estimate])
        .filter(point => point[0] <= cutoff);
  - entity: sensor.hlf_forecast_tomorrow
    name: Forecast Tomorrow
    color: "#ffa94d"
    unit: kWh
    float_precision: 1
    show:
      in_chart: false
      in_header: true
  - entity: sensor.hauslast_taglich
    name: Actual consumption
    color: "#ff4444"
    unit: kWh
    float_precision: 1
    show:
      in_chart: false
      in_header: true
  - entity: sensor.hauslast_stundlich
    name: Actual consumption
    type: column
    color: "#ff4444"
    opacity: 0.5
    unit: kWh
    show:
      legend_value: false
      in_header: false
    group_by:
      func: last
      duration: 1h
    extend_to: now
grid_options:
  columns: full
card_mod:
  style: |
    ha-card {
      box-shadow: none;
      border: none;
    }
```

> **Note:** Replace `sensor.hauslast_taglich` and `sensor.hauslast_stundlich` with your own sensor names. Adjust the `max` value of the Y-axis (`3`) to match your typical consumption.

</details>

---

## Troubleshooting

### Forecast values appear as 0 or fallback

Check the debug log (Settings → System → Logs) for messages like `"Fallback (nur X Tage Daten)"`. The `data_days` attribute on the sensor shows how many days of data are available — at least 10 are required.

### Outliers at certain hours

The `debug_hauslast.py` script can be run directly on the HA host and shows raw values per hour from the statistics database:

```bash
python3 /config/debug_hauslast.py
```

### Icon not displayed

Requires Home Assistant ≥ 2026.3. On older versions the integration icon will be empty.

### Sensor briefly shows old value after restart

This is intentional — the last value is restored via `RestoreEntity` until the dependent sensors (battery, PV) become available again.

---

## Changelog

The full changelog with all versions can be found in [CHANGELOG.md](CHANGELOG.md).

### v1.1.1
- Fixed battery runtime jumps (debounce: only `is_forecast: true` slots used for calculation)
- SOC forecast now always starts at 00:00; past SOC slots are frozen and no longer recalculated
- Added `soc_pct` (0–100 %) to every `soc_hourly_forecast` entry
- New diagnostic sensor `battery_empty_at`: timestamp when battery runs empty, or `false` if it lasts
- House load forecast: fixed missing 00:00 entry
- **Past house load forecast values are now frozen:** Changing parameters (e.g. history weeks) no longer recalculates already past hours retroactively
- **New optional sensor "PV Forecast Day After Tomorrow":** Enables a true 48h forecast from now (instead of ending at 23:00 of the following day)
- SOC simulation extended internally to 72 slots (3 days); output capped at 48h from now
- Dashboard YAMLs updated: time window 00:00 to now+48h, unified %-axis

### v1.1.0
- Sensor names and entity IDs changed to English
- Bilingual settings (German/English)
- Two README files (German + English)

### v1.0.0
- Initial release on HACS

---

## License

MIT License – see [LICENSE](LICENSE)

---

## Acknowledgements

- [Solcast Solar Forecast](https://github.com/BJReplay/ha-solcast-solar) for PV forecasting
- [ApexCharts Card](https://github.com/RomRider/apexcharts-card) for dashboard visualisation
- [homeassistant-alphaESS](https://github.com/CharlesGillanders/homeassistant-alphaESS) by CharlesGillanders for AlphaESS integration
- [Integrating AlphaESS Inverter into Home Assistant via Modbus](https://projects.hillviewlodge.ie/alphaess/) by Projects@Hillview
