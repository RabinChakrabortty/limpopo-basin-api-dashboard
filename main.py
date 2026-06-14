from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import requests
import math

app = FastAPI(
    title="Limpopo River Basin HydroClimate API and Dashboard",
    version="1.0.0",
    description="Automatic online climate, hydrology, flood, drought and environmental monitoring for the Limpopo River Basin."
)

LOCATIONS = {
    "upper_limpopo": {
        "name": "Upper Limpopo",
        "lat": -25.20,
        "lon": 26.90,
        "country": "South Africa / Botswana"
    },
    "middle_limpopo": {
        "name": "Middle Limpopo",
        "lat": -22.20,
        "lon": 29.30,
        "country": "Botswana / South Africa / Zimbabwe"
    },
    "lower_limpopo": {
        "name": "Lower Limpopo",
        "lat": -23.85,
        "lon": 32.55,
        "country": "Mozambique"
    },
    "xai_xai": {
        "name": "Xai-Xai / Lower Limpopo",
        "lat": -25.05,
        "lon": 33.65,
        "country": "Mozambique"
    },
}


def safe_get_json(url, params):
    try:
        response = requests.get(url, params=params, timeout=50)
        response.raise_for_status()
        return response.json()
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


def classify_drought_risk(recent_rain_30d, forecast_rain_7d, forecast_et0_7d):
    if recent_rain_30d is None or forecast_rain_7d is None:
        return "Unknown"

    et0 = forecast_et0_7d or 0

    if recent_rain_30d < 15 and forecast_rain_7d < 5 and et0 > 25:
        return "Very high"
    if recent_rain_30d < 30 and forecast_rain_7d < 10:
        return "High"
    if recent_rain_30d < 60 and forecast_rain_7d < 20:
        return "Moderate"
    return "Low"


def classify_flood_risk(discharge_peak_7d):
    if discharge_peak_7d is None:
        return "Unknown"

    if discharge_peak_7d >= 100:
        return "Very high"
    if discharge_peak_7d >= 50:
        return "High"
    if discharge_peak_7d >= 20:
        return "Moderate"
    return "Low"


def risk_score(risk):
    scores = {
        "Low": 20,
        "Moderate": 50,
        "High": 75,
        "Very high": 95,
        "Unknown": 0
    }
    return scores.get(risk, 0)


def fetch_weather_forecast(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration",
        "forecast_days": 7,
        "timezone": "auto"
    }
    return safe_get_json(url, params)


def fetch_weather_history(lat, lon):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=30)

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum,temperature_2m_mean",
        "timezone": "auto"
    }
    return safe_get_json(url, params)


def fetch_flood_forecast(lat, lon):
    url = "https://flood-api.open-meteo.com/v1/flood"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge",
        "forecast_days": 7,
        "timezone": "auto"
    }
    return safe_get_json(url, params)


def build_location_summary(location_id, meta):
    forecast = fetch_weather_forecast(meta["lat"], meta["lon"])
    history = fetch_weather_history(meta["lat"], meta["lon"])
    flood = fetch_flood_forecast(meta["lat"], meta["lon"])

    forecast_daily = forecast.get("daily", {}) if isinstance(forecast, dict) else {}
    history_daily = history.get("daily", {}) if isinstance(history, dict) else {}
    flood_daily = flood.get("daily", {}) if isinstance(flood, dict) else {}

    forecast_rainfall = forecast_daily.get("precipitation_sum", [])
    forecast_et0 = forecast_daily.get("et0_fao_evapotranspiration", [])
    forecast_tmax = forecast_daily.get("temperature_2m_max", [])
    forecast_tmin = forecast_daily.get("temperature_2m_min", [])

    history_rainfall = history_daily.get("precipitation_sum", [])
    history_temperature = history_daily.get("temperature_2m_mean", [])

    river_discharge = flood_daily.get("river_discharge", [])

    forecast_rain_7d = sum_clean(forecast_rainfall)
    forecast_et0_7d = sum_clean(forecast_et0)
    recent_rain_30d = sum_clean(history_rainfall)
    recent_temp_mean = mean_clean(history_temperature)
    tmax_mean_7d = mean_clean(forecast_tmax)
    tmin_mean_7d = mean_clean(forecast_tmin)
    discharge_peak_7d = max_clean(river_discharge)

    drought_risk = classify_drought_risk(
        recent_rain_30d,
        forecast_rain_7d,
        forecast_et0_7d
    )
    flood_risk = classify_flood_risk(discharge_peak_7d)

    stress_score = round(
        (risk_score(drought_risk) + risk_score(flood_risk)) / 2,
        1
    )

    return {
        "id": location_id,
        "name": meta["name"],
        "country": meta["country"],
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "indicators": {
            "forecast_rainfall_7d_mm": forecast_rain_7d,
            "forecast_et0_7d_mm": forecast_et0_7d,
            "recent_rainfall_30d_mm": recent_rain_30d,
            "recent_mean_temperature_c": recent_temp_mean,
            "forecast_mean_tmax_7d_c": tmax_mean_7d,
            "forecast_mean_tmin_7d_c": tmin_mean_7d,
            "river_discharge_peak_7d_m3s": discharge_peak_7d,
            "drought_risk": drought_risk,
            "flood_risk": flood_risk,
            "water_stress_score_0_100": stress_score
        },
        "forecast_timeseries": {
            "dates": forecast_daily.get("time", []),
            "rainfall_mm": forecast_rainfall,
            "et0_mm": forecast_et0,
            "temperature_max_c": forecast_tmax,
            "temperature_min_c": forecast_tmin
        },
        "history_timeseries": {
            "dates": history_daily.get("time", []),
            "rainfall_mm": history_rainfall,
            "temperature_mean_c": history_temperature
        },
        "flood_timeseries": {
            "dates": flood_daily.get("time", []),
            "river_discharge_m3s": river_discharge
        },
        "data_sources": {
            "weather_forecast": "Open-Meteo Forecast API",
            "weather_history": "Open-Meteo Historical Weather API",
            "river_discharge": "Open-Meteo Flood API / GloFAS"
        },
        "raw_errors": {
            "forecast_error": forecast.get("error") if isinstance(forecast, dict) else None,
            "history_error": history.get("error") if isinstance(history, dict) else None,
            "flood_error": flood.get("error") if isinstance(flood, dict) else None
        }
    }


@app.get("/api/locations")
def api_locations():
    return LOCATIONS


@app.get("/api/location/{location_id}")
def api_location(location_id: str):
    if location_id not in LOCATIONS:
        return {
            "error": "Location not found",
            "available_locations": list(LOCATIONS.keys())
        }

    return build_location_summary(location_id, LOCATIONS[location_id])


@app.get("/api/summary")
def api_summary():
    locations = [
        build_location_summary(location_id, meta)
        for location_id, meta in LOCATIONS.items()
    ]

    rainfall_values = [
        item["indicators"]["forecast_rainfall_7d_mm"]
        for item in locations
        if item["indicators"]["forecast_rainfall_7d_mm"] is not None
    ]

    stress_values = [
        item["indicators"]["water_stress_score_0_100"]
        for item in locations
        if item["indicators"]["water_stress_score_0_100"] is not None
    ]

    return {
        "basin": "Limpopo River Basin",
        "generated_on": date.today().isoformat(),
        "note": "All data are fetched automatically from online APIs. No manual input is required.",
        "basin_indicators": {
            "mean_forecast_rainfall_7d_mm": mean_clean(rainfall_values),
            "mean_water_stress_score_0_100": mean_clean(stress_values)
        },
        "locations": locations
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Limpopo River Basin HydroClimate Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 30px;
            background: #f4f6f8;
            color: #111827;
        }
        h1 {
            color: #0f172a;
            margin-bottom: 6px;
        }
        .card {
            background: white;
            padding: 18px;
            margin: 12px 0;
            border-radius: 10px;
            box-shadow: 0 1px 5px #ddd;
        }
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 12px;
        }
        .metric {
            font-size: 26px;
            font-weight: bold;
            color: #0f172a;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
        }
        th, td {
            padding: 10px;
            border-bottom: 1px solid #ddd;
            text-align: left;
            font-size: 14px;
        }
        th {
            background: #e2e8f0;
        }
        .loading {
            color: #475569;
            font-weight: bold;
        }
        .error {
            color: red;
            font-weight: bold;
        }
        .badge {
            padding: 4px 8px;
            color: white;
            border-radius: 8px;
            font-size: 12px;
            font-weight: bold;
        }
        .Low { background: #16a34a; }
        .Moderate { background: #f59e0b; }
        .High { background: #dc2626; }
        .Veryhigh { background: #7f1d1d; }
        .Unknown { background: #64748b; }
    </style>
</head>
<body>
    <h1>Limpopo River Basin HydroClimate Dashboard</h1>
    <p>Automatic online rainfall, temperature, evapotranspiration, river discharge, flood and drought monitoring.</p>

    <div class="card">
        <h2>API links</h2>
        <p><a href="/api/summary">/api/summary</a></p>
        <p><a href="/api/locations">/api/locations</a></p>
        <p><a href="/docs">/docs</a></p>
    </div>

    <div class="card">
        <h2>Dashboard status</h2>
        <p id="status" class="loading">Loading online data...</p>
    </div>

    <div class="cards">
        <div class="card">
            <h3>Mean 7-day rainfall</h3>
            <div class="metric" id="rainMetric">Loading...</div>
        </div>
        <div class="card">
            <h3>Mean water-stress score</h3>
            <div class="metric" id="stressMetric">Loading...</div>
        </div>
        <div class="card">
            <h3>Data mode</h3>
            <div class="metric">Online</div>
        </div>
        <div class="card">
            <h3>Manual input</h3>
            <div class="metric">None</div>
        </div>
    </div>

    <div class="card">
        <h2>Monitoring summary</h2>
        <table>
            <thead>
                <tr>
                    <th>Location</th>
                    <th>Country/Area</th>
                    <th>Rain 7d mm</th>
                    <th>ET0 7d mm</th>
                    <th>Recent rain 30d mm</th>
                    <th>Mean temp °C</th>
                    <th>Peak discharge 7d m³/s</th>
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

    <div class="card">
        <div id="rainChart"></div>
    </div>

    <div class="card">
        <div id="stressChart"></div>
    </div>

<script>
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

async function loadData() {
    const status = document.getElementById("status");
    const rowsBox = document.getElementById("rows");

    try {
        const res = await fetch("/api/summary");
        const data = await res.json();

        if (!data.locations || data.locations.length === 0) {
            status.innerHTML = "No location data returned.";
            rowsBox.innerHTML = "<tr><td colspan='10'>No data available</td></tr>";
            return;
        }

        document.getElementById("rainMetric").innerHTML =
            fmt(data.basin_indicators.mean_forecast_rainfall_7d_mm) + " mm";

        document.getElementById("stressMetric").innerHTML =
            fmt(data.basin_indicators.mean_water_stress_score_0_100) + " / 100";

        let rows = "";
        let names = [];
        let rain = [];
        let stress = [];
        let discharge = [];

        data.locations.forEach(loc => {
            const i = loc.indicators;

            names.push(loc.name);
            rain.push(i.forecast_rainfall_7d_mm || 0);
            stress.push(i.water_stress_score_0_100 || 0);
            discharge.push(i.river_discharge_peak_7d_m3s || 0);

            rows += `
                <tr>
                    <td>${loc.name}</td>
                    <td>${loc.country}</td>
                    <td>${fmt(i.forecast_rainfall_7d_mm)}</td>
                    <td>${fmt(i.forecast_et0_7d_mm)}</td>
                    <td>${fmt(i.recent_rainfall_30d_mm)}</td>
                    <td>${fmt(i.recent_mean_temperature_c)}</td>
                    <td>${fmt(i.river_discharge_peak_7d_m3s)}</td>
                    <td>${badge(i.drought_risk)}</td>
                    <td>${badge(i.flood_risk)}</td>
                    <td>${fmt(i.water_stress_score_0_100)}</td>
                </tr>
            `;
        });

        rowsBox.innerHTML = rows;
        status.innerHTML = "Online data loaded successfully from Open-Meteo Forecast, Historical Weather and GloFAS-based Flood API.";
        status.className = "";

        Plotly.newPlot("rainChart", [
            {
                x: names,
                y: rain,
                type: "bar",
                name: "7-day rainfall"
            },
            {
                x: names,
                y: discharge,
                type: "bar",
                name: "Peak discharge 7d"
            }
        ], {
            title: "Forecast rainfall and peak river discharge",
            barmode: "group",
            yaxis: { title: "Value" }
        }, {responsive: true});

        Plotly.newPlot("stressChart", [
            {
                x: names,
                y: stress,
                type: "bar",
                name: "Water-stress score"
            }
        ], {
            title: "Water-stress score by monitoring location",
            yaxis: { title: "Score 0-100", range: [0, 100] }
        }, {responsive: true});

    } catch (error) {
        status.innerHTML = "Error loading dashboard data: " + error;
        status.className = "error";
        rowsBox.innerHTML = "<tr><td colspan='10'>Failed to load data</td></tr>";
    }
}

loadData();
</script>
</body>
</html>
"""


@app.get("/health")
def health():
    return {"status": "ok"}
