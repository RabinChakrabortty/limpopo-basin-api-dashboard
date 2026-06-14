from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import requests
import math
import time
from collections import defaultdict

app = FastAPI(
    title="Limpopo River Basin HydroClimate API and Dashboard",
    version="3.0.0",
    description="Professional online climate, hydrology, drought, flood, map and 1-year prediction dashboard for the Limpopo River Basin."
)

CACHE = {}
CACHE_TTL_SECONDS = 6 * 60 * 60

LOCATIONS = {
    "upper_limpopo": {
        "name": "Upper Limpopo",
        "lat": -25.20,
        "lon": 26.90,
        "country": "South Africa / Botswana"
    },
    "gaborone": {
        "name": "Gaborone",
        "lat": -24.65,
        "lon": 25.91,
        "country": "Botswana"
    },
    "francistown": {
        "name": "Francistown",
        "lat": -21.17,
        "lon": 27.51,
        "country": "Botswana"
    },
    "polokwane": {
        "name": "Polokwane",
        "lat": -23.90,
        "lon": 29.45,
        "country": "South Africa"
    },
    "mokopane": {
        "name": "Mokopane",
        "lat": -24.19,
        "lon": 29.01,
        "country": "South Africa"
    },
    "beitbridge": {
        "name": "Beitbridge",
        "lat": -22.22,
        "lon": 30.00,
        "country": "Zimbabwe / South Africa"
    },
    "middle_limpopo": {
        "name": "Middle Limpopo",
        "lat": -22.20,
        "lon": 29.30,
        "country": "Botswana / South Africa / Zimbabwe"
    },
    "massingir": {
        "name": "Massingir",
        "lat": -23.88,
        "lon": 32.16,
        "country": "Mozambique"
    },
    "chokwe": {
        "name": "Chokwe",
        "lat": -24.53,
        "lon": 32.98,
        "country": "Mozambique"
    },
    "xai_xai": {
        "name": "Xai-Xai / Lower Limpopo",
        "lat": -25.05,
        "lon": 33.65,
        "country": "Mozambique"
    },
}


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
        v for v in values
        if isinstance(v, (int, float)) and not math.isnan(v)
    ]


def sum_clean(values):
    clean = clean_numbers(values)
    return round(sum(clean), 2) if clean else None


def mean_clean(values):
    clean = clean_numbers(values)
    return round(sum(clean) / len(clean), 2) if clean else None


def max_clean(values):
    clean = clean_numbers(values)
    return round(max(clean), 2) if clean else None


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
    if rain_mm is None:
        return "Unknown"

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
    if discharge_peak is None:
        return "Unknown"

    if discharge_peak >= 100:
        return "Very high"
    if discharge_peak >= 50:
        return "High"
    if discharge_peak >= 20:
        return "Moderate"
    return "Low"


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


def default_dates():
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=30)
    return start.isoformat(), end.isoformat()


def build_climatology_prediction(lat, lon, horizon_days, history_years):
    horizon_days = clamp(int(horizon_days), 1, 365)
    history = fetch_long_history_for_prediction(lat, lon, history_years)

    daily = history.get("daily", {}) if isinstance(history, dict) else {}

    dates = daily.get("time", [])
    rain = daily.get("precipitation_sum", [])
    temp = daily.get("temperature_2m_mean", [])
    et0 = daily.get("et0_fao_evapotranspiration", [])

    by_day = defaultdict(lambda: {"rain": [], "temp": [], "et0": []})

    for i, d in enumerate(dates):
        try:
            mmdd = d[5:10]
            if i < len(rain) and isinstance(rain[i], (int, float)):
                by_day[mmdd]["rain"].append(rain[i])
            if i < len(temp) and isinstance(temp[i], (int, float)):
                by_day[mmdd]["temp"].append(temp[i])
            if i < len(et0) and isinstance(et0[i], (int, float)):
                by_day[mmdd]["et0"].append(et0[i])
        except Exception:
            continue

    future_dates = []
    pred_rain = []
    pred_temp = []
    pred_et0 = []

    tomorrow = date.today() + timedelta(days=1)

    all_rain = clean_numbers(rain)
    all_temp = clean_numbers(temp)
    all_et0 = clean_numbers(et0)

    fallback_rain = mean_clean(all_rain) or 0
    fallback_temp = mean_clean(all_temp) or 0
    fallback_et0 = mean_clean(all_et0) or 0

    for offset in range(horizon_days):
        future_day = tomorrow + timedelta(days=offset)
        mmdd = future_day.isoformat()[5:10]

        future_dates.append(future_day.isoformat())
        pred_rain.append(round(mean_clean(by_day[mmdd]["rain"]) or fallback_rain, 2))
        pred_temp.append(round(mean_clean(by_day[mmdd]["temp"]) or fallback_temp, 2))
        pred_et0.append(round(mean_clean(by_day[mmdd]["et0"]) or fallback_et0, 2))

    return {
        "dates": future_dates,
        "predicted_rainfall_mm": pred_rain,
        "predicted_temperature_c": pred_temp,
        "predicted_et0_mm": pred_et0,
        "method": f"{history_years}-year daily climatology from Open-Meteo archive",
        "raw_error": history.get("error") if isinstance(history, dict) else None
    }


def get_all_locations(custom_name=None, custom_lat=None, custom_lon=None):
    locations = dict(LOCATIONS)

    if custom_lat is not None and custom_lon is not None:
        try:
            lat = float(custom_lat)
            lon = float(custom_lon)
            name = custom_name or "Custom location"

            locations["custom_location"] = {
                "name": name,
                "lat": lat,
                "lon": lon,
                "country": "User selected"
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

    forecast_rainfall = forecast_daily.get("precipitation_sum", [])
    forecast_et0 = forecast_daily.get("et0_fao_evapotranspiration", [])
    forecast_tmax = forecast_daily.get("temperature_2m_max", [])
    forecast_tmin = forecast_daily.get("temperature_2m_min", [])

    history_rainfall = history_daily.get("precipitation_sum", [])
    history_temperature = history_daily.get("temperature_2m_mean", [])
    history_et0 = history_daily.get("et0_fao_evapotranspiration", [])

    river_discharge = flood_daily.get("river_discharge", [])

    prediction_rainfall = prediction.get("predicted_rainfall_mm", [])
    prediction_temperature = prediction.get("predicted_temperature_c", [])
    prediction_et0 = prediction.get("predicted_et0_mm", [])

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

    drought_risk = classify_drought_risk(prediction_rain_total, prediction_et0_total)
    flood_risk = classify_flood_risk(discharge_peak)

    stress_score = round(
        (risk_score(drought_risk) + risk_score(flood_risk)) / 2,
        1
    )

    water_balance = None
    if prediction_rain_total is not None and prediction_et0_total is not None:
        water_balance = round(prediction_rain_total - prediction_et0_total, 2)

    return {
        "id": location_id,
        "name": meta["name"],
        "country": meta["country"],
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "selected_period": {
            "history_start_date": start_date,
            "history_end_date": end_date,
            "prediction_days": forecast_days,
            "history_years_for_prediction": history_years
        },
        "indicators": {
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
            "short_term_weather_forecast": "Open-Meteo Forecast API",
            "weather_history": "Open-Meteo Historical Weather API",
            "long_term_prediction": "Open-Meteo Historical Archive Daily Climatology",
            "river_discharge": "Open-Meteo Flood API / GloFAS"
        },
        "prediction_note": "The 1-year prediction is a climatology-based prediction using historical online data. It is not a deterministic weather forecast.",
        "raw_errors": {
            "forecast_error": forecast.get("error") if isinstance(forecast, dict) else None,
            "history_error": history.get("error") if isinstance(history, dict) else None,
            "flood_error": flood.get("error") if isinstance(flood, dict) else None,
            "prediction_error": prediction.get("raw_error") if isinstance(prediction, dict) else None
        }
    }


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

    prediction_rain_values = [
        item["indicators"]["predicted_rainfall_total_mm"]
        for item in locations
        if item["indicators"]["predicted_rainfall_total_mm"] is not None
    ]

    stress_values = [
        item["indicators"]["water_stress_score_0_100"]
        for item in locations
        if item["indicators"]["water_stress_score_0_100"] is not None
    ]

    discharge_values = [
        item["indicators"]["river_discharge_peak_m3s"]
        for item in locations
        if item["indicators"]["river_discharge_peak_m3s"] is not None
    ]

    balance_values = [
        item["indicators"]["predicted_water_balance_mm"]
        for item in locations
        if item["indicators"]["predicted_water_balance_mm"] is not None
    ]

    return {
        "basin": "Limpopo River Basin",
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
            "mean_predicted_rainfall_mm": mean_clean(prediction_rain_values),
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


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Limpopo River Basin Professional HydroClimate Dashboard</title>

    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <style>
        body {
            font-family: Inter, Arial, sans-serif;
            margin: 0;
            background: #eef2f7;
            color: #111827;
        }

        .hero {
            background: linear-gradient(135deg, #0f172a, #1e3a8a, #0f766e);
            color: white;
            padding: 28px 34px;
        }

        .hero h1 {
            margin: 0 0 8px 0;
            font-size: 34px;
        }

        .hero p {
            margin: 0;
            color: #dbeafe;
        }

        .container {
            padding: 24px;
        }

        .card {
            background: white;
            padding: 18px;
            margin: 14px 0;
            border-radius: 16px;
            box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
        }

        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 14px;
            align-items: end;
        }

        label {
            font-weight: 700;
            display: block;
            margin-bottom: 6px;
            color: #0f172a;
        }

        input, select, button {
            width: 100%;
            padding: 11px;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            font-size: 14px;
            box-sizing: border-box;
        }

        button {
            background: #0f172a;
            color: white;
            cursor: pointer;
            font-weight: 700;
            border: none;
        }

        button:hover {
            background: #1e293b;
        }

        .tabs {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 14px;
        }

        .tab-button {
            width: auto;
            padding: 11px 18px;
            background: #dbeafe;
            color: #0f172a;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 700;
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
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 14px;
        }

        .metric-card {
            background: linear-gradient(180deg, #ffffff, #f8fafc);
            border-left: 5px solid #2563eb;
        }

        .metric {
            font-size: 28px;
            font-weight: 800;
            color: #0f172a;
        }

        .metric-sub {
            color: #64748b;
            font-size: 13px;
        }

        #map {
            height: 620px;
            width: 100%;
            border-radius: 16px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
        }

        th, td {
            padding: 11px;
            border-bottom: 1px solid #e5e7eb;
            text-align: left;
            font-size: 14px;
        }

        th {
            background: #e2e8f0;
            color: #0f172a;
        }

        .loading {
            color: #2563eb;
            font-weight: 700;
        }

        .error {
            color: #dc2626;
            font-weight: 700;
        }

        .badge {
            padding: 5px 9px;
            color: white;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
            display: inline-block;
        }

        .Low { background: #16a34a; }
        .Moderate { background: #f59e0b; }
        .High { background: #dc2626; }
        .Veryhigh { background: #7f1d1d; }
        .Unknown { background: #64748b; }

        .legend {
            background: white;
            padding: 12px;
            line-height: 24px;
            border-radius: 10px;
            box-shadow: 0 1px 8px #777;
            font-size: 13px;
        }

        .legend span {
            display: inline-block;
            width: 14px;
            height: 14px;
            margin-right: 7px;
            border-radius: 50%;
        }

        pre {
            white-space: pre-wrap;
            background: #0f172a;
            color: #e2e8f0;
            padding: 16px;
            border-radius: 12px;
            max-height: 520px;
            overflow: auto;
        }

        .note {
            background: #fff7ed;
            color: #9a3412;
            padding: 12px;
            border-radius: 12px;
            border-left: 5px solid #f97316;
        }
    </style>
</head>

<body>
    <div class="hero">
        <h1>Limpopo River Basin HydroClimate Intelligence Dashboard</h1>
        <p>Professional online monitoring, mapping and 1-year climate-risk prediction using automatic online data sources.</p>
    </div>

    <div class="container">
        <div class="card">
            <h2>Control panel</h2>

            <div class="controls">
                <div>
                    <label>Historical start date</label>
                    <input type="date" id="startDate">
                </div>

                <div>
                    <label>Historical end date</label>
                    <input type="date" id="endDate">
                </div>

                <div>
                    <label>Prediction horizon</label>
                    <select id="forecastDays">
                        <option value="7">7 days</option>
                        <option value="14">14 days</option>
                        <option value="30">30 days</option>
                        <option value="90">90 days</option>
                        <option value="180">180 days</option>
                        <option value="365" selected>1 year / 365 days</option>
                    </select>
                </div>

                <div>
                    <label>Historical years for prediction</label>
                    <select id="historyYears">
                        <option value="3">3 years</option>
                        <option value="5">5 years</option>
                        <option value="10" selected>10 years</option>
                    </select>
                </div>

                <div>
                    <label>Map variable</label>
                    <select id="mapVariable">
                        <option value="stress">Water-stress score</option>
                        <option value="predicted_rainfall">Predicted rainfall</option>
                        <option value="predicted_et0">Predicted ET0</option>
                        <option value="water_balance">Predicted water balance</option>
                        <option value="predicted_temp">Predicted temperature</option>
                        <option value="discharge">Peak river discharge</option>
                        <option value="drought">Drought risk</option>
                        <option value="flood">Flood risk</option>
                    </select>
                </div>

                <div>
                    <label>Update</label>
                    <button onclick="loadData()">Apply and refresh</button>
                </div>
            </div>

            <h3>Specific custom location</h3>
            <div class="controls">
                <div>
                    <label>Location name</label>
                    <input type="text" id="customName" placeholder="Example: My Station">
                </div>

                <div>
                    <label>Latitude</label>
                    <input type="number" step="0.0001" id="customLat" placeholder="-23.90">
                </div>

                <div>
                    <label>Longitude</label>
                    <input type="number" step="0.0001" id="customLon" placeholder="29.45">
                </div>

                <div>
                    <label>Add custom point</label>
                    <button onclick="loadData()">Load with custom point</button>
                </div>
            </div>

            <p id="status" class="loading">Loading online data...</p>

            <div class="note">
                The 1-year prediction is generated from online historical climatology. It is suitable for planning and climate-risk screening, not exact daily weather forecasting.
            </div>
        </div>

        <div class="tabs">
            <button class="tab-button active" onclick="openTab('overview', this)">Overview</button>
            <button class="tab-button" onclick="openTab('maptab', this)">Professional Map</button>
            <button class="tab-button" onclick="openTab('charts', this)">Professional Plots</button>
            <button class="tab-button" onclick="openTab('timeseries', this)">1-Year Prediction</button>
            <button class="tab-button" onclick="openTab('api', this)">API / JSON</button>
        </div>

        <div id="overview" class="tab-content active">
            <div class="cards">
                <div class="card metric-card">
                    <h3>Mean predicted rainfall</h3>
                    <div class="metric" id="rainMetric">Loading...</div>
                    <div class="metric-sub">Selected prediction horizon</div>
                </div>

                <div class="card metric-card">
                    <h3>Mean water-stress score</h3>
                    <div class="metric" id="stressMetric">Loading...</div>
                    <div class="metric-sub">0 low, 100 extreme</div>
                </div>

                <div class="card metric-card">
                    <h3>Mean water balance</h3>
                    <div class="metric" id="balanceMetric">Loading...</div>
                    <div class="metric-sub">Rainfall minus ET0</div>
                </div>

                <div class="card metric-card">
                    <h3>Mean peak discharge</h3>
                    <div class="metric" id="dischargeMetric">Loading...</div>
                    <div class="metric-sub">Short-term GloFAS-based flood API</div>
                </div>
            </div>

            <div class="card">
                <h2>Monitoring and prediction summary</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Location</th>
                            <th>Country/Area</th>
                            <th>Predicted rain mm</th>
                            <th>Predicted ET0 mm</th>
                            <th>Water balance mm</th>
                            <th>Predicted temp °C</th>
                            <th>Peak discharge m³/s</th>
                            <th>Drought risk</th>
                            <th>Flood risk</th>
                            <th>Stress score</th>
                        </tr>
                    </thead>
                    <tbody id="rows">
                        <tr><td colspan="10">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div id="maptab" class="tab-content">
            <div class="card">
                <h2>Professional interactive Limpopo Basin map</h2>
                <p>Change the map variable in the control panel. Circle color and size update automatically.</p>
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
                <h2>Specific location prediction</h2>
                <select id="locationSelect" onchange="drawTimeSeries()"></select>
            </div>

            <div class="card"><div id="predictionRainChart"></div></div>
            <div class="card"><div id="predictionTempChart"></div></div>
            <div class="card"><div id="predictionBalanceChart"></div></div>
            <div class="card"><div id="floodLineChart"></div></div>
        </div>

        <div id="api" class="tab-content">
            <div class="card">
                <h2>API links</h2>
                <p><a href="/api/summary" target="_blank">/api/summary</a></p>
                <p><a href="/api/locations" target="_blank">/api/locations</a></p>
                <p><a href="/docs" target="_blank">/docs</a></p>
            </div>

            <div class="card">
                <h2>Current API response</h2>
                <pre id="jsonBox">Loading...</pre>
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
    start.setDate(start.getDate() - 31);

    document.getElementById("endDate").value = end.toISOString().slice(0, 10);
    document.getElementById("startDate").value = start.toISOString().slice(0, 10);
}

function openTab(tabId, button) {
    document.querySelectorAll(".tab-content").forEach(tab => tab.classList.remove("active"));
    document.querySelectorAll(".tab-button").forEach(btn => btn.classList.remove("active"));

    document.getElementById(tabId).classList.add("active");
    button.classList.add("active");

    if (tabId === "maptab" && map) {
        setTimeout(() => map.invalidateSize(), 250);
    }
}

function fmt(value) {
    if (value === null || value === undefined) return "N/A";
    if (typeof value === "number") return value.toFixed(2);
    return value;
}

function badge(value) {
    let cls = "Unknown";
    if (value === "Low") cls = "Low";
    if (value === "Moderate") cls = "Moderate";
    if (value === "High") cls = "High";
    if (value === "Very high") cls = "Veryhigh";
    return `<span class="badge ${cls}">${value}</span>`;
}

function riskNumeric(risk) {
    if (risk === "Very high") return 95;
    if (risk === "High") return 75;
    if (risk === "Moderate") return 50;
    if (risk === "Low") return 20;
    return 0;
}

function colorScale(value, maxValue, allowNegative=false) {
    if (value === null || value === undefined) return "#64748b";

    if (allowNegative) {
        if (value < -500) return "#7f1d1d";
        if (value < -250) return "#dc2626";
        if (value < 0) return "#f59e0b";
        return "#16a34a";
    }

    if (maxValue <= 0) return "#64748b";

    const ratio = value / maxValue;

    if (ratio >= 0.80) return "#7f1d1d";
    if (ratio >= 0.60) return "#dc2626";
    if (ratio >= 0.40) return "#f59e0b";
    return "#16a34a";
}

function getMapValue(loc, variable) {
    const i = loc.indicators;

    if (variable === "stress") return i.water_stress_score_0_100 || 0;
    if (variable === "predicted_rainfall") return i.predicted_rainfall_total_mm || 0;
    if (variable === "predicted_et0") return i.predicted_et0_total_mm || 0;
    if (variable === "water_balance") return i.predicted_water_balance_mm || 0;
    if (variable === "predicted_temp") return i.predicted_mean_temperature_c || 0;
    if (variable === "discharge") return i.river_discharge_peak_m3s || 0;
    if (variable === "drought") return riskNumeric(i.drought_risk);
    if (variable === "flood") return riskNumeric(i.flood_risk);

    return 0;
}

function getMapLabel(variable) {
    if (variable === "stress") return "Water-stress score";
    if (variable === "predicted_rainfall") return "Predicted rainfall";
    if (variable === "predicted_et0") return "Predicted ET0";
    if (variable === "water_balance") return "Predicted water balance";
    if (variable === "predicted_temp") return "Predicted temperature";
    if (variable === "discharge") return "Peak river discharge";
    if (variable === "drought") return "Drought risk score";
    if (variable === "flood") return "Flood risk score";
    return "Value";
}

function initMap() {
    map = L.map("map").setView([-23.6, 30.4], 6);

    const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: "OpenStreetMap"
    });

    const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
        maxZoom: 17,
        attribution: "OpenTopoMap"
    });

    osm.addTo(map);

    L.control.layers({
        "OpenStreetMap": osm,
        "Topographic": topo
    }).addTo(map);

    markerLayer = L.layerGroup().addTo(map);

    const riverLine = [
        [-25.20, 26.90],
        [-24.30, 28.30],
        [-22.90, 29.80],
        [-22.22, 30.00],
        [-23.88, 32.16],
        [-24.53, 32.98],
        [-25.05, 33.65]
    ];

    L.polyline(riverLine, {
        color: "#2563eb",
        weight: 4,
        opacity: 0.75
    }).addTo(map).bindPopup("Approximate Limpopo River monitoring corridor");

    const legend = L.control({position: "bottomright"});

    legend.onAdd = function () {
        const div = L.DomUtil.create("div", "legend");
        div.innerHTML = `
            <b>Map intensity</b><br>
            <span style="background:#16a34a"></span> Low / favorable<br>
            <span style="background:#f59e0b"></span> Moderate<br>
            <span style="background:#dc2626"></span> High<br>
            <span style="background:#7f1d1d"></span> Very high<br>
            <span style="background:#64748b"></span> Unknown
        `;
        return div;
    };

    legend.addTo(map);
}

function updateMap() {
    if (!latestData || !map || !markerLayer) return;

    markerLayer.clearLayers();

    const variable = document.getElementById("mapVariable").value;
    const label = getMapLabel(variable);
    const allowNegative = variable === "water_balance";

    const values = latestData.locations.map(loc => Math.abs(getMapValue(loc, variable)));
    const maxValue = Math.max(...values, 1);

    const bounds = [];

    latestData.locations.forEach(loc => {
        const i = loc.indicators;
        const value = getMapValue(loc, variable);
        const color = colorScale(value, maxValue, allowNegative);
        const radius = 8 + 24 * (Math.abs(value) / maxValue);

        const marker = L.circleMarker([loc.latitude, loc.longitude], {
            radius: radius,
            color: color,
            fillColor: color,
            fillOpacity: 0.70,
            weight: 2
        }).addTo(markerLayer);

        marker.bindPopup(`
            <b>${loc.name}</b><br>
            <b>Country/Area:</b> ${loc.country}<br>
            <b>${label}:</b> ${fmt(value)}<br>
            <hr>
            <b>Predicted rainfall:</b> ${fmt(i.predicted_rainfall_total_mm)} mm<br>
            <b>Predicted ET0:</b> ${fmt(i.predicted_et0_total_mm)} mm<br>
            <b>Water balance:</b> ${fmt(i.predicted_water_balance_mm)} mm<br>
            <b>Predicted mean temp:</b> ${fmt(i.predicted_mean_temperature_c)} °C<br>
            <b>Peak discharge:</b> ${fmt(i.river_discharge_peak_m3s)} m³/s<br>
            <b>Drought risk:</b> ${i.drought_risk}<br>
            <b>Flood risk:</b> ${i.flood_risk}<br>
            <b>Water stress:</b> ${fmt(i.water_stress_score_0_100)} / 100
        `);

        bounds.push([loc.latitude, loc.longitude]);
    });

    if (bounds.length > 0) {
        map.fitBounds(bounds, {padding: [40, 40]});
    }
}

async function loadData() {
    const status = document.getElementById("status");
    const rowsBox = document.getElementById("rows");

    const startDate = document.getElementById("startDate").value;
    const endDate = document.getElementById("endDate").value;
    const forecastDays = document.getElementById("forecastDays").value;
    const historyYears = document.getElementById("historyYears").value;

    const customName = encodeURIComponent(document.getElementById("customName").value.trim());
    const customLat = document.getElementById("customLat").value;
    const customLon = document.getElementById("customLon").value;

    status.innerHTML = "Loading online data. For 1-year prediction this may take 30-90 seconds on free Render...";
    status.className = "loading";
    rowsBox.innerHTML = "<tr><td colspan='10'>Loading...</td></tr>";

    let url = `/api/summary?start_date=${startDate}&end_date=${endDate}&forecast_days=${forecastDays}&history_years=${historyYears}`;

    if (customLat && customLon) {
        url += `&custom_name=${customName || "Custom location"}&custom_lat=${customLat}&custom_lon=${customLon}`;
    }

    try {
        const res = await fetch(url);
        const data = await res.json();

        latestData = data;
        document.getElementById("jsonBox").textContent = JSON.stringify(data, null, 2);

        if (!data.locations || data.locations.length === 0) {
            status.innerHTML = "No location data returned.";
            rowsBox.innerHTML = "<tr><td colspan='10'>No data available</td></tr>";
            return;
        }

        document.getElementById("rainMetric").innerHTML =
            fmt(data.basin_indicators.mean_predicted_rainfall_mm) + " mm";

        document.getElementById("stressMetric").innerHTML =
            fmt(data.basin_indicators.mean_water_stress_score_0_100) + " / 100";

        document.getElementById("balanceMetric").innerHTML =
            fmt(data.basin_indicators.mean_predicted_water_balance_mm) + " mm";

        document.getElementById("dischargeMetric").innerHTML =
            fmt(data.basin_indicators.mean_peak_discharge_m3s) + " m³/s";

        let rows = "";
        let names = [];
        let predRain = [];
        let predET0 = [];
        let balance = [];
        let stress = [];
        let discharge = [];

        const locationSelect = document.getElementById("locationSelect");
        locationSelect.innerHTML = "";

        data.locations.forEach((loc, index) => {
            const i = loc.indicators;

            names.push(loc.name);
            predRain.push(i.predicted_rainfall_total_mm || 0);
            predET0.push(i.predicted_et0_total_mm || 0);
            balance.push(i.predicted_water_balance_mm || 0);
            stress.push(i.water_stress_score_0_100 || 0);
            discharge.push(i.river_discharge_peak_m3s || 0);

            const option = document.createElement("option");
            option.value = index;
            option.textContent = loc.name;
            locationSelect.appendChild(option);

            rows += `
                <tr>
                    <td>${loc.name}</td>
                    <td>${loc.country}</td>
                    <td>${fmt(i.predicted_rainfall_total_mm)}</td>
                    <td>${fmt(i.predicted_et0_total_mm)}</td>
                    <td>${fmt(i.predicted_water_balance_mm)}</td>
                    <td>${fmt(i.predicted_mean_temperature_c)}</td>
                    <td>${fmt(i.river_discharge_peak_m3s)}</td>
                    <td>${badge(i.drought_risk)}</td>
                    <td>${badge(i.flood_risk)}</td>
                    <td>${fmt(i.water_stress_score_0_100)}</td>
                </tr>
            `;
        });

        rowsBox.innerHTML = rows;

        updateMap();
        drawSummaryCharts(names, predRain, predET0, balance, stress, discharge);
        drawTimeSeries();

        status.innerHTML = "Online data loaded successfully. Current API: " + url;
        status.className = "";

    } catch (error) {
        status.innerHTML = "Error loading dashboard data: " + error;
        status.className = "error";
        rowsBox.innerHTML = "<tr><td colspan='10'>Failed to load data</td></tr>";
    }
}

function drawSummaryCharts(names, predRain, predET0, balance, stress, discharge) {
    const commonLayout = {
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        font: {family: "Arial", color: "#0f172a"},
        margin: {l: 60, r: 30, t: 70, b: 120}
    };

    Plotly.newPlot("rainChart", [
        {
            x: names,
            y: predRain,
            type: "bar",
            name: "Predicted rainfall",
            marker: {color: "#2563eb"}
        },
        {
            x: names,
            y: predET0,
            type: "bar",
            name: "Predicted ET0",
            marker: {color: "#f97316"}
        }
    ], {
        ...commonLayout,
        title: "Predicted rainfall vs evapotranspiration",
        barmode: "group",
        yaxis: {title: "mm"}
    }, {responsive: true});

    Plotly.newPlot("stressChart", [
        {
            x: names,
            y: stress,
            type: "bar",
            name: "Water-stress score",
            marker: {color: stress.map(v => v >= 75 ? "#7f1d1d" : v >= 50 ? "#dc2626" : v >= 30 ? "#f59e0b" : "#16a34a")}
        }
    ], {
        ...commonLayout,
        title: "Water-stress score by location",
        yaxis: {title: "Score 0-100", range: [0, 100]}
    }, {responsive: true});

    Plotly.newPlot("balanceChart", [
        {
            x: names,
            y: balance,
            type: "bar",
            name: "Water balance",
            marker: {color: balance.map(v => v < 0 ? "#dc2626" : "#16a34a")}
        }
    ], {
        ...commonLayout,
        title: "Predicted water balance: rainfall minus ET0",
        yaxis: {title: "mm"}
    }, {responsive: true});

    Plotly.newPlot("riskScatter", [
        {
            x: predRain,
            y: stress,
            mode: "markers+text",
            type: "scatter",
            text: names,
            textposition: "top center",
            marker: {
                size: discharge.map(v => 10 + Math.min(v, 120) / 3),
                color: stress,
                colorscale: "YlOrRd",
                showscale: true,
                colorbar: {title: "Stress"}
            },
            name: "Locations"
        }
    ], {
        ...commonLayout,
        title: "Risk relationship: predicted rainfall vs water stress",
        xaxis: {title: "Predicted rainfall, mm"},
        yaxis: {title: "Water-stress score"}
    }, {responsive: true});
}

function drawTimeSeries() {
    if (!latestData || !latestData.locations || latestData.locations.length === 0) return;

    const selectedIndex = document.getElementById("locationSelect").value || 0;
    const loc = latestData.locations[selectedIndex];

    const p = loc.prediction_timeseries;
    const flood = loc.flood_timeseries;

    const balance = p.predicted_rainfall_mm.map((r, idx) => {
        const e = p.predicted_et0_mm[idx] || 0;
        return Number((r - e).toFixed(2));
    });

    const commonLayout = {
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        font: {family: "Arial", color: "#0f172a"},
        margin: {l: 60, r: 30, t: 70, b: 80}
    };

    Plotly.newPlot("predictionRainChart", [
        {
            x: p.dates,
            y: p.predicted_rainfall_mm,
            type: "scatter",
            mode: "lines",
            name: "Predicted rainfall",
            line: {color: "#2563eb", width: 2}
        },
        {
            x: p.dates,
            y: p.predicted_et0_mm,
            type: "scatter",
            mode: "lines",
            name: "Predicted ET0",
            line: {color: "#f97316", width: 2}
        }
    ], {
        ...commonLayout,
        title: "1-year predicted rainfall and ET0: " + loc.name,
        yaxis: {title: "mm/day"}
    }, {responsive: true});

    Plotly.newPlot("predictionTempChart", [
        {
            x: p.dates,
            y: p.predicted_temperature_c,
            type: "scatter",
            mode: "lines",
            name: "Predicted temperature",
            line: {color: "#dc2626", width: 2}
        }
    ], {
        ...commonLayout,
        title: "1-year predicted mean temperature: " + loc.name,
        yaxis: {title: "°C"}
    }, {responsive: true});

    Plotly.newPlot("predictionBalanceChart", [
        {
            x: p.dates,
            y: balance,
            type: "scatter",
            mode: "lines",
            name: "Water balance",
            fill: "tozeroy",
            line: {color: "#0f766e", width: 2}
        }
    ], {
        ...commonLayout,
        title: "1-year predicted daily water balance: " + loc.name,
        yaxis: {title: "Rainfall - ET0, mm/day"}
    }, {responsive: true});

    Plotly.newPlot("floodLineChart", [
        {
            x: flood.dates,
            y: flood.river_discharge_m3s,
            type: "scatter",
            mode: "lines+markers",
            name: "River discharge",
            line: {color: "#1e40af", width: 3}
        }
    ], {
        ...commonLayout,
        title: "Short-term river discharge forecast: " + loc.name,
        yaxis: {title: "m³/s"}
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
