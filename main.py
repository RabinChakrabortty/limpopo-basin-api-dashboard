from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import requests
import math
import time
from collections import defaultdict

app = FastAPI(
    title="Limpopo River Basin HydroClimate API and Dashboard",
    version="4.1.0",
    description="Professional multi-temporal Digital Twin dashboard for water resources management and prediction across the Limpopo Basin riparian states."
)

# ============================================================
# GLOBAL CACHE
# ============================================================

CACHE = {}
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours


# ============================================================
# STRATEGIC MONITORING LOCATIONS
# ============================================================

LOCATIONS = {
    "upper_limpopo": {
        "name": "Upper Limpopo Headwaters",
        "lat": -25.20,
        "lon": 26.90,
        "country": "South Africa / Botswana",
        "desc": "Primary runoff generation zone. Highly sensitive to upstream agricultural abstraction."
    },
    "gaborone": {
        "name": "Gaborone Catchment",
        "lat": -24.65,
        "lon": 25.91,
        "country": "Botswana",
        "desc": "Critical municipal supply zone facing infrastructure and climate allocation pressures."
    },
    "francistown": {
        "name": "Francistown / Shashe Sub-Basin",
        "lat": -21.17,
        "lon": 27.51,
        "country": "Botswana",
        "desc": "Ephemeral tributary hub feeding major water storage frameworks."
    },
    "polokwane": {
        "name": "Polokwane Regional Platform",
        "lat": -23.90,
        "lon": 29.45,
        "country": "South Africa",
        "desc": "High groundwater abstraction area with major urban and mining demands."
    },
    "mokopane": {
        "name": "Mokopane Mogalakwena System",
        "lat": -24.19,
        "lon": 29.01,
        "country": "South Africa",
        "desc": "Inland sub-catchment showing rapid evapotranspiration transitions."
    },
    "beitbridge": {
        "name": "Beitbridge Transboundary Gateway",
        "lat": -22.22,
        "lon": 30.00,
        "country": "Zimbabwe / South Africa",
        "desc": "Strategic international monitoring corridor for cross-border flow verification."
    },
    "middle_limpopo": {
        "name": "Middle Limpopo Main Stem",
        "lat": -22.20,
        "lon": 29.30,
        "country": "Botswana / South Africa / Zimbabwe",
        "desc": "Alluvial aquifer storage valley where river losses to groundwater can be significant."
    },
    "massingir": {
        "name": "Massingir Dam Operations",
        "lat": -23.88,
        "lon": 32.16,
        "country": "Mozambique",
        "desc": "Downstream infrastructure focal point regulating cross-border flood wave propagation."
    },
    "chokwe": {
        "name": "Chokwe Irrigation Zone",
        "lat": -24.53,
        "lon": 32.98,
        "country": "Mozambique",
        "desc": "Large delta agriculture sector vulnerable to low-flow and flood conditions."
    },
    "xai_xai": {
        "name": "Xai-Xai / Lower Limpopo Mouth",
        "lat": -25.05,
        "lon": 33.65,
        "country": "Mozambique",
        "desc": "Ocean discharge point, vulnerable to low-flow salinity intrusion and flood routing."
    },
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def cache_key(url, params):
    ordered = tuple(sorted(params.items()))
    return str((url, ordered))


def safe_get_json(url, params):
    key = cache_key(url, params)
    now = time.time()

    if key in CACHE:
        created, data = CACHE[key]
        if now - created < CACHE_TTL_SECONDS:
            return data

    try:
        response = requests.get(url, params=params, timeout=80)
        response.raise_for_status()
        data = response.json()
        CACHE[key] = (now, data)
        return data
    except Exception as e:
        return {"error": str(e), "url": url, "params": params}


def clean_numbers(values):
    if not values:
        return []
    return [
        value for value in values
        if isinstance(value, (int, float)) and not math.isnan(value)
    ]


def sum_clean(values):
    clean = clean_numbers(values)
    return round(sum(clean), 2) if clean else 0.0


def mean_clean(values):
    clean = clean_numbers(values)
    return round(sum(clean) / len(clean), 2) if clean else 0.0


def max_clean(values):
    clean = clean_numbers(values)
    return round(max(clean), 2) if clean else 0.0


def clamp(value, low, high):
    return max(low, min(high, value))


def risk_score(risk):
    scores = {
        "Low": 20,
        "Moderate": 50,
        "High": 75,
        "Very high": 95,
        "Unknown": 0
    }
    return scores.get(risk, 0)


def classify_drought_risk(rain_mm, et0_mm):
    et0 = et0_mm or 0
    balance = rain_mm - et0

    if rain_mm < 25 and balance < -150:
        return "Very high"
    if rain_mm < 60 and balance < -80:
        return "High"
    if rain_mm < 120 and balance < -30:
        return "Moderate"
    return "Low"


def classify_flood_risk(discharge_peak):
    if discharge_peak >= 100:
        return "Very high"
    if discharge_peak >= 50:
        return "High"
    if discharge_peak >= 20:
        return "Moderate"
    return "Low"


def calculate_antecedent_precipitation(history_rainfall_series, days=90):
    clean_rain = clean_numbers(history_rainfall_series)

    if not clean_rain:
        return 0.0

    if len(clean_rain) < days:
        return round(sum(clean_rain), 2)

    return round(sum(clean_rain[-days:]), 2)


def default_dates():
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=90)
    return start.isoformat(), end.isoformat()


# ============================================================
# ONLINE DATA FETCHERS
# ============================================================

def fetch_weather_forecast(lat, lon, forecast_days):
    forecast_days = clamp(int(forecast_days), 1, 16)

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration",
        "forecast_days": forecast_days,
        "timezone": "auto"
    }

    return safe_get_json(url, params)


def fetch_weather_history(lat, lon, start_date, end_date):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration",
        "timezone": "auto"
    }

    return safe_get_json(url, params)


def fetch_long_history_for_prediction(lat, lon, history_years):
    history_years = clamp(int(history_years), 3, 10)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=365 * history_years)

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration",
        "timezone": "auto"
    }

    return safe_get_json(url, params)


def fetch_flood_forecast(lat, lon, forecast_days):
    forecast_days = clamp(int(forecast_days), 1, 30)

    url = "https://flood-api.open-meteo.com/v1/flood"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge",
        "forecast_days": forecast_days,
        "timezone": "auto"
    }

    return safe_get_json(url, params)


# ============================================================
# PREDICTION ENGINE
# ============================================================

def build_climatology_prediction(lat, lon, horizon_days, history_years):
    horizon_days = clamp(int(horizon_days), 1, 365)
    history = fetch_long_history_for_prediction(lat, lon, history_years)

    daily = history.get("daily", {}) if isinstance(history, dict) else {}

    dates = daily.get("time", [])
    rain = daily.get("precipitation_sum", [])
    temp = daily.get("temperature_2m_mean", [])
    et0 = daily.get("et0_fao_evapotranspiration", [])

    by_day = defaultdict(lambda: {"rain": [], "temp": [], "et0": []})

    for i, day_value in enumerate(dates):
        try:
            mmdd = day_value[5:10]

            if i < len(rain) and isinstance(rain[i], (int, float)):
                by_day[mmdd]["rain"].append(rain[i])

            if i < len(temp) and isinstance(temp[i], (int, float)):
                by_day[mmdd]["temp"].append(temp[i])

            if i < len(et0) and isinstance(et0[i], (int, float)):
                by_day[mmdd]["et0"].append(et0[i])

        except Exception:
            continue

    fallback_rain = mean_clean(rain)
    fallback_temp = mean_clean(temp)
    fallback_et0 = mean_clean(et0)

    future_dates = []
    predicted_rainfall = []
    predicted_temperature = []
    predicted_et0 = []

    tomorrow = date.today() + timedelta(days=1)

    for offset in range(horizon_days):
        future_day = tomorrow + timedelta(days=offset)
        mmdd = future_day.isoformat()[5:10]

        future_dates.append(future_day.isoformat())
        predicted_rainfall.append(round(mean_clean(by_day[mmdd]["rain"]) or fallback_rain, 2))
        predicted_temperature.append(round(mean_clean(by_day[mmdd]["temp"]) or fallback_temp, 2))
        predicted_et0.append(round(mean_clean(by_day[mmdd]["et0"]) or fallback_et0, 2))

    return {
        "dates": future_dates,
        "predicted_rainfall_mm": predicted_rainfall,
        "predicted_temperature_c": predicted_temperature,
        "predicted_et0_mm": predicted_et0,
        "method": f"{history_years}-year daily climatology from online historical archive",
        "raw_error": history.get("error") if isinstance(history, dict) else None
    }


# ============================================================
# DATA ASSEMBLY
# ============================================================

def get_all_locations(custom_name=None, custom_lat=None, custom_lon=None):
    locations = dict(LOCATIONS)

    if custom_lat is not None and custom_lon is not None:
        try:
            locations["custom_location"] = {
                "name": custom_name or "Custom Tracking Station",
                "lat": float(custom_lat),
                "lon": float(custom_lon),
                "country": "User Specified",
                "desc": "User-defined monitoring node added dynamically to the Limpopo Basin dashboard."
            }
        except Exception:
            pass

    return locations


def build_location_summary(location_id, meta, start_date, end_date, forecast_days, history_years):
    forecast_days = clamp(int(forecast_days), 1, 365)

    short_forecast_days = min(forecast_days, 16)
    flood_days = min(forecast_days, 30)

    forecast = fetch_weather_forecast(meta["lat"], meta["lon"], short_forecast_days)
    history = fetch_weather_history(meta["lat"], meta["lon"], start_date, end_date)
    flood = fetch_flood_forecast(meta["lat"], meta["lon"], flood_days)
    prediction = build_climatology_prediction(meta["lat"], meta["lon"], forecast_days, history_years)

    forecast_daily = forecast.get("daily", {}) if isinstance(forecast, dict) else {}
    history_daily = history.get("daily", {}) if isinstance(history, dict) else {}
    flood_daily = flood.get("daily", {}) if isinstance(flood, dict) else {}

    forecast_rainfall = forecast_daily.get("precipitation_sum", []) or []
    forecast_et0 = forecast_daily.get("et0_fao_evapotranspiration", []) or []
    forecast_tmax = forecast_daily.get("temperature_2m_max", []) or []
    forecast_tmin = forecast_daily.get("temperature_2m_min", []) or []

    history_rainfall = history_daily.get("precipitation_sum", []) or []
    history_temperature = history_daily.get("temperature_2m_mean", []) or []
    history_et0 = history_daily.get("et0_fao_evapotranspiration", []) or []

    river_discharge = flood_daily.get("river_discharge", []) or []

    prediction_rainfall = prediction.get("predicted_rainfall_mm", []) or []
    prediction_et0 = prediction.get("predicted_et0_mm", []) or []
    prediction_temperature = prediction.get("predicted_temperature_c", []) or []

    recent_90_day_rain = calculate_antecedent_precipitation(history_rainfall, days=90)

    forecast_rain_total = sum_clean(forecast_rainfall)
    forecast_et0_total = sum_clean(forecast_et0)

    history_rain_total = sum_clean(history_rainfall)
    history_et0_total = sum_clean(history_et0)

    prediction_rain_total = sum_clean(prediction_rainfall)
    prediction_et0_total = sum_clean(prediction_et0)
    prediction_temp_mean = mean_clean(prediction_temperature)

    history_temp_mean = mean_clean(history_temperature)
    tmax_mean_forecast = mean_clean(forecast_tmax)
    tmin_mean_forecast = mean_clean(forecast_tmin)
    discharge_peak = max_clean(river_discharge)

    base_drought_risk = classify_drought_risk(prediction_rain_total, prediction_et0_total)

    if recent_90_day_rain < 45.0 and base_drought_risk == "Moderate":
        drought_risk = "High"
    else:
        drought_risk = base_drought_risk

    flood_risk = classify_flood_risk(discharge_peak)

    stress_score = round(
        (risk_score(drought_risk) * 0.6) + (risk_score(flood_risk) * 0.4),
        1
    )

    water_balance = round(prediction_rain_total - prediction_et0_total, 2)

    return {
        "id": location_id,
        "name": meta["name"],
        "country": meta["country"],
        "description": meta["desc"],
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "selected_period": {
            "history_start_date": start_date,
            "history_end_date": end_date,
            "prediction_days": forecast_days,
            "history_years_for_prediction": history_years
        },
        "indicators": {
            "recent_90_day_accumulated_rainfall_mm": recent_90_day_rain,
            "short_term_forecast_rainfall_mm": forecast_rain_total,
            "short_term_forecast_et0_mm": forecast_et0_total,
            "history_rainfall_total_mm": history_rain_total,
            "history_et0_total_mm": history_et0_total,
            "history_mean_temperature_c": history_temp_mean,
            "short_term_forecast_mean_tmax_c": tmax_mean_forecast,
            "short_term_forecast_mean_tmin_c": tmin_mean_forecast,
            "predicted_rainfall_total_mm": prediction_rain_total,
            "predicted_et0_total_mm": prediction_et0_total,
            "predicted_mean_temperature_c": prediction_temp_mean,
            "predicted_water_balance_mm": water_balance,
            "river_discharge_peak_m3s": discharge_peak,
            "drought_risk": drought_risk,
            "flood_risk": flood_risk,
            "water_stress_score_0_100": stress_score
        },
        "short_term_forecast_timeseries": {
            "dates": forecast_daily.get("time", []),
            "rainfall_mm": forecast_rainfall,
            "et0_mm": forecast_et0,
            "temperature_max_c": forecast_tmax,
            "temperature_min_c": forecast_tmin
        },
        "history_timeseries": {
            "dates": history_daily.get("time", []),
            "rainfall_mm": history_rainfall,
            "temperature_mean_c": history_temperature,
            "et0_mm": history_et0
        },
        "prediction_timeseries": prediction,
        "flood_timeseries": {
            "dates": flood_daily.get("time", []),
            "river_discharge_m3s": river_discharge
        },
        "data_sources": {
            "short_term_weather": "Open-Meteo Forecast API",
            "climatology_history": "Open-Meteo Historical Archive",
            "discharge_routing": "Open-Meteo Flood API / GloFAS-based discharge"
        },
        "prediction_note": "The 1-year prediction uses historical daily climatology from online archive data. It is not a deterministic daily weather forecast.",
        "raw_errors": {
            "forecast_error": forecast.get("error") if isinstance(forecast, dict) else None,
            "history_error": history.get("error") if isinstance(history, dict) else None,
            "flood_error": flood.get("error") if isinstance(flood, dict) else None,
            "prediction_error": prediction.get("raw_error") if isinstance(prediction, dict) else None
        }
    }


# ============================================================
# API ROUTES
# ============================================================

@app.get("/api/locations")
def api_locations():
    return LOCATIONS


@app.get("/api/summary")
def api_summary(
    start_date: str = Query(None),
    end_date: str = Query(None),
    forecast_days: int = Query(365),
    history_years: int = Query(10),
    custom_name: str = Query(None),
    custom_lat: float = Query(None),
    custom_lon: float = Query(None)
):
    if start_date is None or end_date is None:
        start_date, end_date = default_dates()

    forecast_days = clamp(int(forecast_days), 1, 365)
    history_years = clamp(int(history_years), 3, 10)

    locations_dict = get_all_locations(custom_name, custom_lat, custom_lon)

    locations = [
        build_location_summary(location_id, meta, start_date, end_date, forecast_days, history_years)
        for location_id, meta in locations_dict.items()
    ]

    rain_values = [location["indicators"]["predicted_rainfall_total_mm"] for location in locations]
    stress_values = [location["indicators"]["water_stress_score_0_100"] for location in locations]
    discharge_values = [location["indicators"]["river_discharge_peak_m3s"] for location in locations]
    balance_values = [location["indicators"]["predicted_water_balance_mm"] for location in locations]

    return {
        "basin": "Limpopo River Basin System Network",
        "generated_on": date.today().isoformat(),
        "note": "All data are fetched automatically from online APIs. No manual data upload is required.",
        "prediction_note": "For 1-year prediction, the app uses historical daily climatology from online archive data.",
        "selected_period": {
            "history_start_date": start_date,
            "history_end_date": end_date,
            "prediction_days": forecast_days,
            "history_years_for_prediction": history_years
        },
        "basin_indicators": {
            "mean_predicted_rainfall_mm": mean_clean(rain_values),
            "mean_water_stress_score_0_100": mean_clean(stress_values),
            "mean_peak_discharge_m3s": mean_clean(discharge_values),
            "mean_predicted_water_balance_mm": mean_clean(balance_values)
        },
        "locations": locations
    }


@app.get("/api/location/{location_id}")
def api_location(
    location_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    forecast_days: int = Query(365),
    history_years: int = Query(10)
):
    if start_date is None or end_date is None:
        start_date, end_date = default_dates()

    if location_id not in LOCATIONS:
        return {
            "error": "Location not found",
            "available_locations": list(LOCATIONS.keys())
        }

    return build_location_summary(
        location_id,
        LOCATIONS[location_id],
        start_date,
        end_date,
        forecast_days,
        history_years
    )


# ============================================================
# DASHBOARD ROUTE
# ============================================================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Limpopo Transboundary Basin Digital Twin Interface</title>

    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <style>
        body {
            font-family: Inter, Arial, sans-serif;
            margin: 0;
            background: #f1f5f9;
            color: #0f172a;
        }

        .hero {
            background: linear-gradient(135deg, #1e293b, #0f172a, #0d9488);
            color: white;
            padding: 30px;
        }

        .hero h1 {
            margin: 0 0 5px 0;
            font-size: 30px;
            letter-spacing: -0.5px;
        }

        .hero p {
            margin: 0;
            color: #cbd5e1;
            font-size: 15px;
        }

        .container {
            padding: 25px;
        }

        .card {
            background: white;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
        }

        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 15px;
            align-items: end;
        }

        label {
            font-weight: 600;
            font-size: 13px;
            display: block;
            margin-bottom: 5px;
            color: #334155;
        }

        input, select, button {
            width: 100%;
            padding: 10px;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            font-size: 14px;
            box-sizing: border-box;
        }

        button {
            background: #0f172a;
            color: white;
            cursor: pointer;
            font-weight: 600;
            border: none;
            transition: background 0.2s;
        }

        button:hover {
            background: #334155;
        }

        .tabs {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 15px 0;
        }

        .tab-button {
            width: auto;
            padding: 10px 20px;
            background: #e2e8f0;
            color: #334155;
            border-radius: 6px;
            font-weight: 600;
        }

        .tab-button.active {
            background: #0f172a;
            color: white;
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px;
        }

        .metric-card {
            border-left: 5px solid #0d9488;
            background: white;
        }

        .metric {
            font-size: 26px;
            font-weight: 700;
            color: #0f172a;
            margin-top: 5px;
        }

        .metric-sub {
            color: #64748b;
            font-size: 12px;
            margin-top: 2px;
        }

        #map {
            height: 580px;
            width: 100%;
            border-radius: 8px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }

        th, td {
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
            text-align: left;
            font-size: 13px;
        }

        th {
            background: #f8fafc;
            color: #475569;
            font-weight: 600;
        }

        .loading {
            color: #2563eb;
            font-weight: 600;
        }

        .error {
            color: #dc2626;
            font-weight: 600;
        }

        .badge {
            padding: 4px 8px;
            color: white;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            display: inline-block;
        }

        .Low { background: #10b981; }
        .Moderate { background: #f59e0b; }
        .High { background: #f97316; }
        .Veryhigh { background: #ef4444; }
        .Unknown { background: #94a3b8; }

        .legend {
            background: white;
            padding: 10px;
            border-radius: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.1);
            line-height: 18px;
            font-size: 12px;
        }

        .legend span {
            display: inline-block;
            width: 12px;
            height: 12px;
            margin-right: 5px;
            border-radius: 50%;
        }

        pre {
            background: #1e293b;
            color: #f8fafc;
            padding: 15px;
            border-radius: 8px;
            max-height: 450px;
            overflow: auto;
            font-size: 12px;
        }

        .note {
            background: #fef3c7;
            color: #92400e;
            padding: 12px;
            border-radius: 6px;
            border-left: 4px solid #f59e0b;
            font-size: 13px;
            margin-top: 10px;
        }

        .matrix-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 12px;
            margin-top: 10px;
        }

        .matrix-box {
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-top: 4px solid #3b82f6;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        }
    </style>
</head>

<body>
    <div class="hero">
        <h1>Limpopo Transboundary River Basin Digital Twin</h1>
        <p>Operational Hydro-Meteorological Scenario Analysis System using online environmental data sources</p>
    </div>

    <div class="container">
        <div class="card">
            <h2>Multi-Temporal Horizon Control Console</h2>

            <div class="controls">
                <div>
                    <label>Antecedent baseline start</label>
                    <input type="date" id="startDate">
                </div>

                <div>
                    <label>Baseline evaluation end</label>
                    <input type="date" id="endDate">
                </div>

                <div>
                    <label>Prediction scenario horizon</label>
                    <select id="forecastDays">
                        <option value="7">Short-term: 7 days</option>
                        <option value="30">Sub-seasonal: 30 days</option>
                        <option value="90">Seasonal outlook: 90 days</option>
                        <option value="180">Mid-term anomaly: 180 days</option>
                        <option value="365" selected>Strategic target: 1 year</option>
                    </select>
                </div>

                <div>
                    <label>Climatological baseline depth</label>
                    <select id="historyYears">
                        <option value="3">3-year trend profile</option>
                        <option value="5">5-year cyclic mean</option>
                        <option value="10" selected>10-year climatological mean</option>
                    </select>
                </div>

                <div>
                    <label>Map variable</label>
                    <select id="mapVariable">
                        <option value="stress">Composite water stress index</option>
                        <option value="predicted_rainfall">Modeled cumulative rainfall</option>
                        <option value="predicted_et0">Evapotranspiration demand</option>
                        <option value="water_balance">Net water balance</option>
                        <option value="predicted_temp">Projected temperature</option>
                        <option value="discharge">Peak simulated stream runoff</option>
                    </select>
                </div>

                <div>
                    <button onclick="loadData()">Sync Digital Twin</button>
                </div>
            </div>

            <h3 style="margin-top:20px; font-size:15px; color:#475569;">Insert dynamic node point</h3>

            <div class="controls">
                <input type="text" id="customName" placeholder="Node name, e.g. Olifants Sub-Catchment">
                <input type="number" step="0.01" id="customLat" placeholder="Latitude, e.g. -24.0">
                <input type="number" step="0.01" id="customLon" placeholder="Longitude, e.g. 31.5">
                <button onclick="loadData()">Inject Node Layer</button>
            </div>

            <p id="status" class="loading" style="margin-top:15px;"></p>

            <div class="note">
                The 1-year prediction is generated from online historical climatology. It is useful for planning and climate-risk screening, not exact daily weather forecasting.
            </div>
        </div>

        <div class="tabs">
            <button class="tab-button active" onclick="openTab('overview', this)">System Overview</button>
            <button class="tab-button" onclick="openTab('maptab', this)">Spatial Integration Map</button>
            <button class="tab-button" onclick="openTab('charts', this)">Hydrological Comparative Plots</button>
            <button class="tab-button" onclick="openTab('timeseries', this)">Multi-Horizon Projections</button>
            <button class="tab-button" onclick="openTab('api', this)">JSON Infrastructure Feed</button>
        </div>

        <div id="overview" class="tab-content active">
            <div class="card" style="background: #f8fafc; border-left: 5px solid #0f766e;">
                <h3 style="margin:0; font-size:16px; color:#0f172a;">Temporal Decision Matrix</h3>

                <div class="matrix-grid">
                    <div class="matrix-box" style="border-top-color: #2563eb;">
                        <strong style="color:#2563eb; font-size:14px;">Short-term, 1–7 days</strong>
                        <p style="margin:5px 0 0 0; font-size:12px; color:#64748b;">
                            Tracks short-term rainfall, ET0 and river discharge forecast signals.
                        </p>
                    </div>

                    <div class="matrix-box" style="border-top-color: #f97316;">
                        <strong style="color:#f97316; font-size:14px;">Seasonal outlook, 30–90 days</strong>
                        <p style="margin:5px 0 0 0; font-size:12px; color:#64748b;">
                            Evaluates rainfall deficit, evapotranspiration pressure and agricultural water stress.
                        </p>
                    </div>

                    <div class="matrix-box" style="border-top-color: #0d9488;">
                        <strong style="color:#0d9488; font-size:14px;">Strategic window, 1 year</strong>
                        <p style="margin:5px 0 0 0; font-size:12px; color:#64748b;">
                            Estimates long-horizon water balance and drought risk from historical climatology.
                        </p>
                    </div>
                </div>
            </div>

            <div class="cards">
                <div class="card metric-card">
                    <h3>Mean Predicted Rainfall</h3>
                    <div class="metric" id="rainMetric">---</div>
                    <div class="metric-sub">Basin-wide aggregate for target horizon</div>
                </div>

                <div class="card metric-card" style="border-left-color: #ea580c;">
                    <h3>Mean Water Stress Index</h3>
                    <div class="metric" id="stressMetric">---</div>
                    <div class="metric-sub">Scale: 0 low, 100 critical</div>
                </div>

                <div class="card metric-card" style="border-left-color: #0284c7;">
                    <h3>Mean Predicted Net Balance</h3>
                    <div class="metric" id="balanceMetric">---</div>
                    <div class="metric-sub">Accumulated rainfall minus ET0</div>
                </div>

                <div class="card metric-card" style="border-left-color: #b45309;">
                    <h3>Mean Peak Discharge</h3>
                    <div class="metric" id="dischargeMetric">---</div>
                    <div class="metric-sub">Short-term GloFAS-based forecast</div>
                </div>
            </div>

            <div class="card">
                <h2>Transboundary Gauging Station Matrix</h2>

                <div style="overflow-x:auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Monitoring Station</th>
                                <th>Riparian Jurisdiction</th>
                                <th>Antecedent 90d Rain</th>
                                <th>Scenario Rain</th>
                                <th>Scenario ET0</th>
                                <th>Net Balance</th>
                                <th>Peak Runoff</th>
                                <th>Drought Index</th>
                                <th>Flood Hazard</th>
                                <th>Stress Index</th>
                            </tr>
                        </thead>

                        <tbody id="rows">
                            <tr><td colspan="10">Waiting for data synchronisation cycle...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div id="maptab" class="tab-content">
            <div class="card">
                <h2>Spatial Integration Network Grid Map</h2>
                <div id="map"></div>
            </div>
        </div>

        <div id="charts" class="tab-content">
            <div class="card"><div id="rainChart"></div></div>
            <div class="card"><div id="stressChart"></div></div>
            <div class="card"><div id="balanceChart"></div></div>
            <div class="card"><div id="riskScatter"></div></div>
        </div>

        <div id="timeseries" class="tab-content">
            <div class="card">
                <h2>Isolate node temporal coordinates</h2>
                <select id="locationSelect" onchange="drawTimeSeries()"></select>
            </div>

            <div class="card"><div id="predictionRainChart"></div></div>
            <div class="card"><div id="predictionBalanceChart"></div></div>
            <div class="card"><div id="floodLineChart"></div></div>
        </div>

        <div id="api" class="tab-content">
            <div class="card">
                <h2>Operational Pipeline Integration Gateways</h2>
                <p><a href="/api/summary" target="_blank">Integrated Summary Endpoint: /api/summary</a></p>
                <p><a href="/api/locations" target="_blank">Static Metadata Registry: /api/locations</a></p>
                <p><a href="/docs" target="_blank">Swagger API Documentation: /docs</a></p>
            </div>

            <div class="card">
                <h2>Live Reactive Data State</h2>
                <pre id="jsonBox">In transit...</pre>
            </div>
        </div>
    </div>

    <script>
        let map;
        let markerLayer;
        let latestData = null;

        function setDefaultDates() {
            const end = new Date();
            end.setDate(end.getDate() - 1);

            const start = new Date();
            start.setDate(start.getDate() - 91);

            document.getElementById("endDate").value = end.toISOString().slice(0, 10);
            document.getElementById("startDate").value = start.toISOString().slice(0, 10);
        }

        function openTab(tabId, button) {
            document.querySelectorAll(".tab-content").forEach(tab => tab.classList.remove("active"));
            document.querySelectorAll(".tab-button").forEach(btn => btn.classList.remove("active"));

            document.getElementById(tabId).classList.add("active");
            button.classList.add("active");

            if (tabId === "maptab" && map) {
                setTimeout(() => map.invalidateSize(), 200);
            }
        }

        function fmt(value) {
            if (value === null || value === undefined) return "N/A";
            return typeof value === "number" ? value.toFixed(2) : value;
        }

        function badge(value) {
            const cls = value === "Very high" ? "Veryhigh" : value;
            return `<span class="badge ${cls || "Unknown"}">${value}</span>`;
        }

        function colorScale(value, maxValue, allowNegative=false) {
            if (value === null || value === undefined) return "#64748b";

            if (allowNegative) {
                if (value < -200) return "#ef4444";
                if (value < 0) return "#f59e0b";
                return "#10b981";
            }

            const ratio = maxValue <= 0 ? 0 : value / maxValue;

            if (ratio >= 0.80) return "#ef4444";
            if (ratio >= 0.55) return "#f97316";
            if (ratio >= 0.30) return "#f59e0b";
            return "#10b981";
        }

        function getMapValue(location, variable) {
            const indicators = location.indicators;

            if (variable === "stress") return indicators.water_stress_score_0_100 || 0;
            if (variable === "predicted_rainfall") return indicators.predicted_rainfall_total_mm || 0;
            if (variable === "predicted_et0") return indicators.predicted_et0_total_mm || 0;
            if (variable === "water_balance") return indicators.predicted_water_balance_mm || 0;
            if (variable === "predicted_temp") return indicators.predicted_mean_temperature_c || 0;
            if (variable === "discharge") return indicators.river_discharge_peak_m3s || 0;

            return 0;
        }

        function initMap() {
            map = L.map("map").setView([-23.5, 30.0], 6);

            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                attribution: "OpenStreetMap contributors"
            }).addTo(map);

            markerLayer = L.layerGroup().addTo(map);

            const corridor = [
                [-25.20, 26.90],
                [-24.65, 25.91],
                [-21.17, 27.51],
                [-22.22, 30.00],
                [-23.88, 32.16],
                [-24.53, 32.98],
                [-25.05, 33.65]
            ];

            L.polyline(corridor, {
                color: "#0284c7",
                weight: 3,
                opacity: 0.6,
                dashArray: "5, 10"
            }).addTo(map).bindPopup("Approximate Limpopo Basin monitoring corridor");

            const legend = L.control({position: "bottomright"});

            legend.onAdd = function () {
                const div = L.DomUtil.create("div", "legend");

                div.innerHTML = `
                    <strong>Map Legend</strong><br>
                    <span style="background:#10b981"></span> Low / favorable<br>
                    <span style="background:#f59e0b"></span> Advisory<br>
                    <span style="background:#f97316"></span> High anomaly<br>
                    <span style="background:#ef4444"></span> Severe constraint
                `;

                return div;
            };

            legend.addTo(map);
        }

        function updateMap() {
            if (!latestData || !map || !markerLayer) return;

            markerLayer.clearLayers();

            const variable = document.getElementById("mapVariable").value;
            const allowNegative = variable === "water_balance";
            const values = latestData.locations.map(location => Math.abs(getMapValue(location, variable)));
            const maxValue = Math.max(...values, 1);
            const bounds = [];

            latestData.locations.forEach(location => {
                const value = getMapValue(location, variable);
                const color = colorScale(value, maxValue, allowNegative);
                const radius = 10 + 20 * (Math.abs(value) / maxValue);

                const marker = L.circleMarker([location.latitude, location.longitude], {
                    radius: radius,
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.65,
                    weight: 1.5
                }).addTo(markerLayer);

                marker.bindPopup(`
                    <strong style="font-size:14px; color:#0f172a;">${location.name}</strong><br>
                    <small style="color:#64748b;">${location.country}</small><br>
                    <p style="margin:5px 0; font-size:12px; color:#334155;">${location.description}</p>
                    <hr style="border:0; border-top:1px solid #e2e8f0; margin:8px 0;">
                    <b>90d antecedent rainfall:</b> ${fmt(location.indicators.recent_90_day_accumulated_rainfall_mm)} mm<br>
                    <b>Scenario rainfall:</b> ${fmt(location.indicators.predicted_rainfall_total_mm)} mm<br>
                    <b>Scenario ET0:</b> ${fmt(location.indicators.predicted_et0_total_mm)} mm<br>
                    <b>Water balance:</b> ${fmt(location.indicators.predicted_water_balance_mm)} mm<br>
                    <b>Peak discharge:</b> ${fmt(location.indicators.river_discharge_peak_m3s)} m³/s<br>
                    <b>Drought risk:</b> ${badge(location.indicators.drought_risk)}<br>
                    <b>Flood risk:</b> ${badge(location.indicators.flood_risk)}<br>
                    <b>Stress rating:</b> <strong>${fmt(location.indicators.water_stress_score_0_100)} / 100</strong>
                `);

                bounds.push([location.latitude, location.longitude]);
            });

            if (bounds.length > 0) {
                map.fitBounds(bounds, {padding: [40, 40]});
            }
        }

        async function loadData() {
            const status = document.getElementById("status");
            const rows = document.getElementById("rows");

            status.innerHTML = "Processing online data requests. A 1-year prediction may take 30–90 seconds on Render Free...";
            status.className = "loading";

            rows.innerHTML = "<tr><td colspan='10'>Loading online data...</td></tr>";

            const startDate = document.getElementById("startDate").value;
            const endDate = document.getElementById("endDate").value;
            const forecastDays = document.getElementById("forecastDays").value;
            const historyYears = document.getElementById("historyYears").value;

            const customName = encodeURIComponent(document.getElementById("customName").value.trim());
            const customLat = document.getElementById("customLat").value;
            const customLon = document.getElementById("customLon").value;

            let endpoint = `/api/summary?start_date=${startDate}&end_date=${endDate}&forecast_days=${forecastDays}&history_years=${historyYears}`;

            if (customLat && customLon) {
                endpoint += `&custom_name=${customName || "Inserted Node Layer"}&custom_lat=${customLat}&custom_lon=${customLon}`;
            }

            try {
                const response = await fetch(endpoint);
                const data = await response.json();

                latestData = data;

                document.getElementById("jsonBox").textContent = JSON.stringify(data, null, 2);

                document.getElementById("rainMetric").textContent =
                    fmt(data.basin_indicators.mean_predicted_rainfall_mm) + " mm";

                document.getElementById("stressMetric").textContent =
                    fmt(data.basin_indicators.mean_water_stress_score_0_100) + " / 100";

                document.getElementById("balanceMetric").textContent =
                    fmt(data.basin_indicators.mean_predicted_water_balance_mm) + " mm";

                document.getElementById("dischargeMetric").textContent =
                    fmt(data.basin_indicators.mean_peak_discharge_m3s) + " m³/s";

                let htmlBuffer = "";
                let names = [];
                let rains = [];
                let et0s = [];
                let balances = [];
                let stresses = [];
                let flows = [];

                const selector = document.getElementById("locationSelect");
                selector.innerHTML = "";

                data.locations.forEach((location, index) => {
                    const indicators = location.indicators;

                    names.push(location.name);
                    rains.push(indicators.predicted_rainfall_total_mm || 0);
                    et0s.push(indicators.predicted_et0_total_mm || 0);
                    balances.push(indicators.predicted_water_balance_mm || 0);
                    stresses.push(indicators.water_stress_score_0_100 || 0);
                    flows.push(indicators.river_discharge_peak_m3s || 0);

                    const option = document.createElement("option");
                    option.value = index;
                    option.textContent = location.name;
                    selector.appendChild(option);

                    htmlBuffer += `
                        <tr>
                            <td><strong>${location.name}</strong></td>
                            <td><small>${location.country}</small></td>
                            <td>${fmt(indicators.recent_90_day_accumulated_rainfall_mm)}</td>
                            <td>${fmt(indicators.predicted_rainfall_total_mm)}</td>
                            <td>${fmt(indicators.predicted_et0_total_mm)}</td>
                            <td style="font-weight:600; color:${indicators.predicted_water_balance_mm < 0 ? "#ef4444" : "#10b981"};">
                                ${fmt(indicators.predicted_water_balance_mm)}
                            </td>
                            <td>${fmt(indicators.river_discharge_peak_m3s)}</td>
                            <td>${badge(indicators.drought_risk)}</td>
                            <td>${badge(indicators.flood_risk)}</td>
                            <td><strong>${fmt(indicators.water_stress_score_0_100)}</strong></td>
                        </tr>
                    `;
                });

                rows.innerHTML = htmlBuffer;

                updateMap();
                drawSummaryCharts(names, rains, et0s, balances, stresses, flows);
                drawTimeSeries();

                status.innerHTML = "Digital Twin Network synchronised successfully.";
                status.className = "";

            } catch (error) {
                status.innerHTML = "Pipeline exception: " + error;
                status.className = "error";
                rows.innerHTML = "<tr><td colspan='10' style='color:#ef4444;'>Failed to synchronise data.</td></tr>";
            }
        }

        function drawSummaryCharts(names, rains, et0s, balances, stresses, flows) {
            const layout = {
                paper_bgcolor: "white",
                plot_bgcolor: "white",
                font: {
                    family: "Inter, Arial, sans-serif",
                    color: "#0f172a"
                },
                margin: {
                    l: 55,
                    r: 25,
                    t: 55,
                    b: 95
                }
            };

            Plotly.newPlot("rainChart", [
                {
                    x: names,
                    y: rains,
                    type: "bar",
                    name: "Predicted rainfall",
                    marker: {color: "#0284c7"}
                },
                {
                    x: names,
                    y: et0s,
                    type: "bar",
                    name: "Predicted ET0",
                    marker: {color: "#f97316"}
                }
            ], {
                ...layout,
                title: "Scenario Budget Metrics: Rainfall vs Evapotranspiration",
                barmode: "group",
                yaxis: {title: "mm"}
            }, {responsive: true});

            Plotly.newPlot("stressChart", [
                {
                    x: names,
                    y: stresses,
                    type: "bar",
                    marker: {
                        color: stresses.map(score => score > 65 ? "#ef4444" : score > 45 ? "#f97316" : "#10b981")
                    }
                }
            ], {
                ...layout,
                title: "Water Stress Score Distribution",
                yaxis: {range: [0, 100], title: "Score 0–100"}
            }, {responsive: true});

            Plotly.newPlot("balanceChart", [
                {
                    x: names,
                    y: balances,
                    type: "bar",
                    marker: {
                        color: balances.map(balance => balance < 0 ? "#ef4444" : "#10b981")
                    }
                }
            ], {
                ...layout,
                title: "Net Hydro-Deficit / Water Balance",
                yaxis: {title: "Rainfall - ET0, mm"}
            }, {responsive: true});

            Plotly.newPlot("riskScatter", [
                {
                    x: rains,
                    y: stresses,
                    mode: "markers+text",
                    text: names,
                    textposition: "top center",
                    marker: {
                        size: flows.map(flow => 12 + Math.min(flow, 150) / 4),
                        color: stresses,
                        colorscale: "Portland",
                        showscale: true,
                        colorbar: {title: "Stress"}
                    }
                }
            ], {
                ...layout,
                title: "Risk Relationship: Rainfall Mass vs Water Stress",
                xaxis: {title: "Predicted rainfall, mm"},
                yaxis: {title: "Water stress score"}
            }, {responsive: true});
        }

        function drawTimeSeries() {
            if (!latestData || !latestData.locations || latestData.locations.length === 0) return;

            const selectedIndex = document.getElementById("locationSelect").value || 0;
            const node = latestData.locations[selectedIndex];

            const forecast = node.short_term_forecast_timeseries;
            const prediction = node.prediction_timeseries;
            const flood = node.flood_timeseries;

            const forecastDates = forecast.dates || [];
            const predictionDates = prediction.dates || [];

            const forecastRainfall = forecast.rainfall_mm || [];
            const forecastET0 = forecast.et0_mm || [];

            const predictionRainfall = prediction.predicted_rainfall_mm || [];
            const predictionET0 = prediction.predicted_et0_mm || [];

            const allDates = [...forecastDates, ...predictionDates];
            const allRainfall = [...forecastRainfall, ...predictionRainfall];
            const allET0 = [...forecastET0, ...predictionET0];

            const balanceValues = allRainfall.map((rainValue, index) => {
                const et0Value = allET0[index] || 0;
                return Number((rainValue - et0Value).toFixed(2));
            });

            const layout = {
                paper_bgcolor: "white",
                plot_bgcolor: "white",
                font: {
                    family: "Inter, Arial, sans-serif",
                    color: "#0f172a"
                },
                margin: {
                    l: 55,
                    r: 30,
                    t: 55,
                    b: 55
                },
                xaxis: {gridcolor: "#f1f5f9"},
                yaxis: {gridcolor: "#f1f5f9"}
            };

            Plotly.newPlot("predictionRainChart", [
                {
                    x: forecastDates,
                    y: forecastRainfall,
                    type: "scatter",
                    mode: "lines",
                    name: "Short-term forecast rainfall",
                    line: {color: "#2563eb", width: 2.5}
                },
                {
                    x: predictionDates,
                    y: predictionRainfall,
                    type: "scatter",
                    mode: "lines",
                    name: "1-year climatology rainfall",
                    line: {color: "#0284c7", width: 1.5, dash: "dash"}
                },
                {
                    x: allDates,
                    y: allET0,
                    type: "scatter",
                    mode: "lines",
                    name: "ET0 demand",
                    line: {color: "#ef4444", width: 1.5}
                }
            ], {
                ...layout,
                title: `Multi-temporal Meteorology Profile: ${node.name}`,
                yaxis: {title: "mm/day"}
            }, {responsive: true});

            Plotly.newPlot("predictionBalanceChart", [
                {
                    x: allDates,
                    y: balanceValues,
                    type: "scatter",
                    mode: "lines",
                    fill: "tozeroy",
                    name: "Net rainfall - ET0",
                    line: {color: "#0d9488"}
                }
            ], {
                ...layout,
                title: `Continuous Water Balance Pattern: ${node.name}`,
                yaxis: {title: "Net balance, mm/day"}
            }, {responsive: true});

            Plotly.newPlot("floodLineChart", [
                {
                    x: flood.dates || [],
                    y: flood.river_discharge_m3s || [],
                    type: "scatter",
                    mode: "lines+markers",
                    name: "River discharge",
                    line: {color: "#1e40af", width: 2.5}
                }
            ], {
                ...layout,
                title: `Short-term River Discharge Forecast: ${node.name}`,
                yaxis: {title: "Discharge, m³/s"}
            }, {responsive: true});
        }

        document.getElementById("mapVariable").addEventListener("change", updateMap);

        setDefaultDates();
        initMap();
        loadData();
    </script>
</body>
</html>
    """


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
