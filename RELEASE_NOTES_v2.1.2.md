# v2.1.2 – Forecast Current Hour & Forecast Next Hour

## 🆕 Neue Sensoren / New Sensors

### `sensor.hlf_forecast_current_hour` – Forecast Current Hour
Prognostizierter Hauslast-Verbrauch der **aktuellen Stunde** (kWh).
Forecasted house load consumption for the **current hour** (kWh).

- Liest den `load_estimate` der aktuellen vollen Stunde aus `forecast_heute`
- Reads the `load_estimate` of the current full hour from `forecast_heute`
- Attribute / Attributes: `hour`, `load_estimate_w`
- Icon: `mdi:home-clock`
- `state_class: MEASUREMENT` → HA-Langzeitstatistik / HA long-term statistics

### `sensor.hlf_forecast_next_hour` – Forecast Next Hour
Prognostizierter Hauslast-Verbrauch der **nächsten Stunde** (kWh).
Forecasted house load consumption for the **next hour** (kWh).

- Bei Stunde 23 wird automatisch auf `forecast_morgen[0]` (00:00 morgen) zurückgegriffen
- At hour 23, automatically falls back to `forecast_morgen[0]` (00:00 tomorrow)
- Attribute / Attributes: `hour`, `is_tomorrow`, `load_estimate_w`
- Icon: `mdi:home-clock-outline`
- `state_class: MEASUREMENT` → HA-Langzeitstatistik / HA long-term statistics

## 🔧 Sonstiges / Other

- Übersetzungen in allen Sprachdateien ergänzt (strings.json, translations/de.json, translations/en.json)
- Translations added to all language files (strings.json, translations/de.json, translations/en.json)

## 📋 Anwendungsbeispiele / Usage Examples

Die neuen Sensoren eignen sich z. B. für:
The new sensors are useful for:

- **Automationen:** Waschmaschine oder Geschirrspüler starten, wenn die prognostizierte Hauslast der nächsten Stunde niedrig ist
- **Automations:** Start washing machine or dishwasher when the forecasted load for the next hour is low
- **Dashboard-Anzeige:** Aktuelle und kommende Stundenprognose direkt als Entitätskarte anzeigen
- **Dashboard display:** Show current and upcoming hourly forecast directly as entity card
- **Schwellenwert-Benachrichtigungen:** Warnung wenn die prognostizierte Last einer Stunde ungewöhnlich hoch ist
- **Threshold notifications:** Alert when the forecasted load for an hour is unusually high

## ⬆️ Update

HACS → Integrationen → Hauslast Prognose → Aktualisieren → HA neu starten.
HACS → Integrations → Hauslast Prognose → Update → Restart HA.

Die neuen Sensoren erscheinen automatisch auf der Geräteseite.
The new sensors appear automatically on the device page.
