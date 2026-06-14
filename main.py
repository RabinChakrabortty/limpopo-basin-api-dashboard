from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import requests
import statistics
import math

app = FastAPI(
    title="Limpopo River Basin HydroClimate API and Dashboard",
    version="1.0.0"
)

LOCATIONS = {
    "upper_limpopo": {"name": "Upper Limpopo", "lat": -25.20, "lon": 26.90},
    "middle_limpopo": {"name": "Middle Limpopo", "lat": -22.20, "lon": 29.30},
    "lower_limpopo": {"name": "Lower Limpopo", "lat": -23.85, "lon": 32.55},
    "xai_xai": {"name": "Xai-Xai / Lower Limpopo", "lat": -25.05, "lon": 33.65},
}

def safe_get_json(url, params):
    try:
        r = requests.get(url, params=params, timeout=40)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def sum_clean(values):
    clean = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return sum(clean) if clean else None

def mean_clean(values):
    clean = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return sum(clean) / len(clean) if clean else None

def max_clean(values):
    clean = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    return max(clean) if clean else None

def classify_risk(value):
    if value is None:
        return "Unknown"
    if value >= 70:
        return "High"
    if value >= 40:
        return "Moderate"
    return "Low"

def get_forecast(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration",
        "forecast_days": 7,
        "timezone": "auto"
    }
    return safe_get_json(url, params)

def get_history(lat, lon):
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

def get_flood(lat, lon):
    url = "https://flood-api.open-meteo.com/v1/flood"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge",
        "forecast_days": 7,
        "timezone": "auto"
    }
    return safe_get_json(url, params)

def build_summary(location_id, meta):
    forecast = get_forecast(meta["lat"], meta["lon"])
    history = get_history(meta["lat"], meta["lon"])
    flood = get_flood(meta["lat"], meta["lon"])

    forecast_daily = forecast.get("daily", {})
    history_daily = history.get("daily", {})
    flood_daily = flood.get("daily", {})

    rain_7d = sum_clean(forecast_daily.get("precipitation_sum", []))
    et0_7d = sum_clean(forecast_daily.get("et0_fao_evapotranspiration", []))
    recent_rain_30d = sum_clean(history_daily.get("precipitation_sum", []))
    discharge_peak_7d = max_clean(flood_daily.get("river_discharge", []))

    drought_score = 0
    if recent_rain_30d is not None:
        drought_score = max(0, 100 - recent_rain_30d)

    flood_score = 0
    if discharge_peak_7d is not None:
        flood_score = min(100, discharge_peak_7d / 10)

    stress_score = min(100, round((drought_score + flood_score) / 2, 1))

    return {
        "id": location_id,
        "name": meta["name"],
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "indicators": {
            "forecast_rainfall_7d_mm": rain_7d,
            "forecast_et0_7d_mm": et0_7d,
            "recent_rainfall_30d_mm": recent_rain_30d,
            "river_discharge_peak_7d_m3s": discharge_peak_7d,
            "drought_risk": classify_risk(drought_score),
            "flood_risk": classify_risk(flood_score),
            "water_stress_score_0_100": stress_score,
        },
        "forecast_timeseries": forecast_daily,
        "history_timeseries": history_daily,
        "flood_timeseries": flood_daily,
        "data_sources": [
            "Open-Meteo Forecast API",
            "Open-Meteo Historical Weather API",
            "Open-Meteo Flood API / GloFAS"
        ]
    }

@app.get("/api/locations")
def api_locations():
    return LOCATIONS

@app.get("/api/location/{location_id}")
def api_location(location_id: str):
    if location_id not in LOCATIONS:
        return {"error": "Location not found", "available": list(LOCATIONS.keys())}
    return build_summary(location_id, LOCATIONS[location_id])

@app.get("/api/summary")
def api_summary():
    locations = [build_summary(k, v) for k, v in LOCATIONS.items()]
    return {
        "basin": "Limpopo River Basin",
        "generated_on": date.today().isoformat(),
        "note": "All data are fetched automatically from online APIs. No manual input is required.",
        "locations": locations
    }

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Limpopo River Basin Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 30px; background: #f4f6f8; }
        h1 { color: #0f172a; }
        .card { background: white; padding: 18px; margin: 12px 0; border-radius: 10px; box-shadow: 0 1px 5px #ddd; }
        table { width: 100%; border-collapse: collapse; background: white; }
        th, td { padding: 10px; border-bottom: 1px solid #ddd; text-align: left; }
        th { background: #e2e8f0; }
    </style>
</head>
<body>
    <h1>Limpopo River Basin HydroClimate Dashboard</h1>
    <p>Automatic online rainfall, temperature, evapotranspiration, flood and drought monitoring.</p>

    <div class="card">
        <h2>API links</h2>
        <p><a href="/api/summary">/api/summary</a></p>
        <p><a href="/api/locations">/api/locations</a></p>
        <p><a href="/docs">/docs</a></p>
    </div>

    <div class="card">
        <h2>Monitoring summary</h2>
        <table>
            <thead>
                <tr>
                    <th>Location</th>
                    <th>Rain 7d mm</th>
                    <th>ET0 7d mm</th>
                    <th>Peak discharge 7d</th>
                    <th>Drought risk</th>
                    <th>Flood risk</th>
                    <th>Stress score</th>
                </tr>
            </thead>
            <tbody id="rows"></tbody>
        </table>
    </div>

    <div class="card">
        <div id="rainChart"></div>
    </div>

<script>
async function loadData() {
    const res = await fetch('/api/summary');
    const data = await res.json();

    let rows = "";
    let names = [];
    let rain = [];
    let stress = [];

    data.locations.forEach(loc => {
        const i = loc.indicators;
        names.push(loc.name);
        rain.push(i.forecast_rainfall_7d_mm || 0);
        stress.push(i.water_stress_score_0_100 || 0);

        rows += `
            <tr>
                <td>${loc.name}</td>
                <td>${i.forecast_rainfall_7d_mm}</td>
                <td>${i.forecast_et0_7d_mm}</td>
                <td>${i.river_discharge_peak_7d_m3s}</td>
                <td>${i.drought_risk}</td>
                <td>${i.flood_risk}</td>
                <td>${i.water_stress_score_0_100}</td>
            </tr>
        `;
    });

    document.getElementById("rows").innerHTML = rows;

    Plotly.newPlot("rainChart", [
        { x: names, y: rain, type: "bar", name: "7-day rainfall" },
        { x: names, y: stress, type: "bar", name: "Water stress score" }
    ], {
        title: "Limpopo Basin forecast rainfall and water-stress score",
        barmode: "group"
    });
}

loadData();
</script>
</body>
</html>
"""

@app.get("/health")
def health():
    return {"status": "ok"}
