from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import requests
import math

app = FastAPI(
    title="Limpopo River Basin HydroClimate API and Dashboard",
    version="2.0.0",
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
        response = requests.get(url, params=params, timeout=60)
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


def clamp(value, low, high):
    return max(low, min(high, value))


def classify_drought_risk(recent_rain_mm, forecast_rain_mm, forecast_et0_mm):
    if recent_rain_mm is None or forecast_rain_mm is None:
        return "Unknown"

    et0 = forecast_et0_mm or 0

    if recent_rain_mm < 15 and forecast_rain_mm < 5 and et0 > 25:
        return "Very high"
    if recent_rain_mm < 30 and forecast_rain_mm < 10:
        return "High"
    if recent_rain_mm < 60 and forecast_rain_mm < 20:
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


def risk_score(risk):
    scores = {
        "Low": 20,
        "Moderate": 50,
        "High": 75,
        "Very high": 95,
        "Unknown": 0
    }
    return scores.get(risk, 0)


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


def build_location_summary(location_id, meta, start_date, end_date, forecast_days):
    forecast = fetch_weather_forecast(meta["lat"], meta["lon"], forecast_days)
    history = fetch_weather_history(meta["lat"], meta["lon"], start_date, end_date)
    flood = fetch_flood_forecast(meta["lat"], meta["lon"], forecast_days)

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

    forecast_rain_total = sum_clean(forecast_rainfall)
    forecast_et0_total = sum_clean(forecast_et0)
    history_rain_total = sum_clean(history_rainfall)
    history_et0_total = sum_clean(history_et0)

    recent_temp_mean = mean_clean(history_temperature)
    tmax_mean_forecast = mean_clean(forecast_tmax)
    tmin_mean_forecast = mean_clean(forecast_tmin)
    discharge_peak = max_clean(river_discharge)

    drought_risk = classify_drought_risk(
        history_rain_total,
        forecast_rain_total,
        forecast_et0_total
    )
    flood_risk = classify_flood_risk(discharge_peak)

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
        "selected_period": {
            "history_start_date": start_date,
            "history_end_date": end_date,
            "forecast_days": forecast_days
        },
        "indicators": {
            "forecast_rainfall_total_mm": forecast_rain_total,
            "forecast_et0_total_mm": forecast_et0_total,
            "history_rainfall_total_mm": history_rain_total,
            "history_et0_total_mm": history_et0_total,
            "history_mean_temperature_c": recent_temp_mean,
            "forecast_mean_tmax_c": tmax_mean_forecast,
            "forecast_mean_tmin_c": tmin_mean_forecast,
            "river_discharge_peak_m3s": discharge_peak,
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
            "temperature_mean_c": history_temperature,
            "et0_mm": history_et0
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
def api_location(
    location_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
    forecast_days: int = Query(7)
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
        forecast_days
    )


@app.get("/api/summary")
def api_summary(
    start_date: str = Query(None),
    end_date: str = Query(None),
    forecast_days: int = Query(7)
):
    if start_date is None or end_date is None:
        start_date, end_date = default_dates()

    forecast_days = clamp(int(forecast_days), 1, 30)

    locations = [
        build_location_summary(location_id, meta, start_date, end_date, forecast_days)
        for location_id, meta in LOCATIONS.items()
    ]

    rainfall_values = [
        item["indicators"]["forecast_rainfall_total_mm"]
        for item in locations
        if item["indicators"]["forecast_rainfall_total_mm"] is not None
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

    return {
        "basin": "Limpopo River Basin",
        "generated_on": date.today().isoformat(),
        "note": "All data are fetched automatically from online APIs. No manual input is required.",
        "selected_period": {
            "history_start_date": start_date,
            "history_end_date": end_date,
            "forecast_days": forecast_days
        },
        "basin_indicators": {
            "mean_forecast_rainfall_mm": mean_clean(rainfall_values),
            "mean_water_stress_score_0_100": mean_clean(stress_values),
            "mean_peak_discharge_m3s": mean_clean(discharge_values)
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

    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 24px;
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
            border-radius: 12px;
            box-shadow: 0 1px 5px #ddd;
        }

        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            align-items: end;
        }

        label {
            font-weight: bold;
            display: block;
            margin-bottom: 6px;
        }

        input, select, button {
            width: 100%;
            padding: 10px;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            font-size: 14px;
        }

        button {
            background: #0f172a;
            color: white;
            cursor: pointer;
            font-weight: bold;
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
            padding: 10px 16px;
            background: #e2e8f0;
            color: #0f172a;
            border: none;
            border-radius: 8px;
            cursor: pointer;
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
            gap: 12px;
        }

        .metric {
            font-size: 26px;
            font-weight: bold;
            color: #0f172a;
        }

        #map {
            height: 560px;
            width: 100%;
            border-radius: 10px;
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

        .legend {
            background: white;
            padding: 10px;
            line-height: 22px;
            border-radius: 8px;
            box-shadow: 0 1px 5px #999;
            font-size: 13px;
        }

        .legend span {
            display: inline-block;
            width: 14px;
            height: 14px;
            margin-right: 6px;
            border-radius: 50%;
        }

        pre {
            white-space: pre-wrap;
            background: #0f172a;
            color: #e2e8f0;
            padding: 16px;
            border-radius: 10px;
            max-height: 500px;
            overflow: auto;
        }
    </style>
</head>

<body>
    <h1>Limpopo River Basin HydroClimate Dashboard</h1>
    <p>Automatic online rainfall, temperature, evapotranspiration, river discharge, flood and drought monitoring.</p>

    <div class="card">
        <h2>Change time period and forecast window</h2>

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
                <label>Forecast days</label>
                <select id="forecastDays">
                    <option value="3">3 days</option>
                    <option value="7" selected>7 days</option>
                    <option value="14">14 days</option>
                    <option value="30">30 days</option>
                </select>
            </div>

            <div>
                <label>Map variable</label>
                <select id="mapVariable">
                    <option value="stress">Water-stress score</option>
                    <option value="rainfall">Forecast rainfall</option>
                    <option value="history_rainfall">Historical rainfall</option>
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

        <p id="status" class="loading">Loading online data...</p>
    </div>

    <div class="tabs">
        <button class="tab-button active" onclick="openTab('overview')">Overview</button>
        <button class="tab-button" onclick="openTab('maptab')">Map</button>
        <button class="tab-button" onclick="openTab('charts')">Charts</button>
        <button class="tab-button" onclick="openTab('timeseries')">Time-series</button>
        <button class="tab-button" onclick="openTab('api')">API / JSON</button>
    </div>

    <div id="overview" class="tab-content active">
        <div class="cards">
            <div class="card">
                <h3>Mean forecast rainfall</h3>
                <div class="metric" id="rainMetric">Loading...</div>
            </div>

            <div class="card">
                <h3>Mean water-stress score</h3>
                <div class="metric" id="stressMetric">Loading...</div>
            </div>

            <div class="card">
                <h3>Mean peak discharge</h3>
                <div class="metric" id="dischargeMetric">Loading...</div>
            </div>

            <div class="card">
                <h3>Data mode</h3>
                <div class="metric">Online</div>
            </div>
        </div>

        <div class="card">
            <h2>Monitoring summary</h2>
            <table>
                <thead>
                    <tr>
                        <th>Location</th>
                        <th>Country/Area</th>
                        <th>Forecast rain mm</th>
                        <th>Historical rain mm</th>
                        <th>Forecast ET0 mm</th>
                        <th>Mean temp °C</th>
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
            <h2>Interactive Limpopo Basin map</h2>
            <p>The map updates when you change dates, forecast days, or map variable.</p>
            <div id="map"></div>
        </div>
    </div>

    <div id="charts" class="tab-content">
        <div class="card">
            <div id="rainChart"></div>
        </div>

        <div class="card">
            <div id="stressChart"></div>
        </div>

        <div class="card">
            <div id="dischargeChart"></div>
        </div>
    </div>

    <div id="timeseries" class="tab-content">
        <div class="card">
            <h2>Time-series location</h2>
            <select id="locationSelect" onchange="drawTimeSeries()"></select>
        </div>

        <div class="card">
            <div id="historyRainChart"></div>
        </div>

        <div class="card">
            <div id="forecastRainChart"></div>
        </div>

        <div class="card">
            <div id="floodLineChart"></div>
        </div>
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

function openTab(tabId) {
    document.querySelectorAll(".tab-content").forEach(tab => {
        tab.classList.remove("active");
    });

    document.querySelectorAll(".tab-button").forEach(button => {
        button.classList.remove("active");
    });

    document.getElementById(tabId).classList.add("active");
    event.target.classList.add("active");

    if (tabId === "maptab" && map) {
        setTimeout(() => {
            map.invalidateSize();
        }, 250);
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

function colorScale(value, maxValue) {
    if (value === null || value === undefined) return "#64748b";
    if (maxValue <= 0) return "#64748b";

    const ratio = value / maxValue;

    if (ratio >= 0.8) return "#7f1d1d";
    if (ratio >= 0.6) return "#dc2626";
    if (ratio >= 0.4) return "#f59e0b";
    return "#16a34a";
}

function getMapValue(loc, variable) {
    const i = loc.indicators;

    if (variable === "stress") return i.water_stress_score_0_100 || 0;
    if (variable === "rainfall") return i.forecast_rainfall_total_mm || 0;
    if (variable === "history_rainfall") return i.history_rainfall_total_mm || 0;
    if (variable === "discharge") return i.river_discharge_peak_m3s || 0;
    if (variable === "drought") return riskNumeric(i.drought_risk);
    if (variable === "flood") return riskNumeric(i.flood_risk);

    return 0;
}

function getMapLabel(variable) {
    if (variable === "stress") return "Water-stress score";
    if (variable === "rainfall") return "Forecast rainfall";
    if (variable === "history_rainfall") return "Historical rainfall";
    if (variable === "discharge") return "Peak discharge";
    if (variable === "drought") return "Drought risk score";
    if (variable === "flood") return "Flood risk score";
    return "Value";
}

function initMap() {
    map = L.map("map").setView([-23.8, 30.4], 6);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: "© OpenStreetMap contributors"
    }).addTo(map);

    markerLayer = L.layerGroup().addTo(map);

    const legend = L.control({position: "bottomright"});

    legend.onAdd = function () {
        const div = L.DomUtil.create("div", "legend");
        div.innerHTML = `
            <b>Map color</b><br>
            <span style="background:#16a34a"></span> Low<br>
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

    const values = latestData.locations.map(loc => getMapValue(loc, variable));
    const maxValue = Math.max(...values, 1);

    const bounds = [];

    latestData.locations.forEach(loc => {
        const i = loc.indicators;
        const value = getMapValue(loc, variable);
        const color = colorScale(value, maxValue);
        const radius = 8 + 24 * (value / maxValue);

        const marker = L.circleMarker([loc.latitude, loc.longitude], {
            radius: radius,
            color: color,
            fillColor: color,
            fillOpacity: 0.68,
            weight: 2
        }).addTo(markerLayer);

        marker.bindPopup(`
            <b>${loc.name}</b><br>
            <b>Country/Area:</b> ${loc.country}<br>
            <b>${label}:</b> ${fmt(value)}<br>
            <hr>
            <b>Forecast rainfall:</b> ${fmt(i.forecast_rainfall_total_mm)} mm<br>
            <b>Historical rainfall:</b> ${fmt(i.history_rainfall_total_mm)} mm<br>
            <b>Forecast ET0:</b> ${fmt(i.forecast_et0_total_mm)} mm<br>
            <b>Peak river discharge:</b> ${fmt(i.river_discharge_peak_m3s)} m³/s<br>
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

    status.innerHTML = "Loading online data...";
    status.className = "loading";
    rowsBox.innerHTML = "<tr><td colspan='10'>Loading...</td></tr>";

    const url = `/api/summary?start_date=${startDate}&end_date=${endDate}&forecast_days=${forecastDays}`;

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
            fmt(data.basin_indicators.mean_forecast_rainfall_mm) + " mm";

        document.getElementById("stressMetric").innerHTML =
            fmt(data.basin_indicators.mean_water_stress_score_0_100) + " / 100";

        document.getElementById("dischargeMetric").innerHTML =
            fmt(data.basin_indicators.mean_peak_discharge_m3s) + " m³/s";

        let rows = "";
        let names = [];
        let forecastRain = [];
        let historyRain = [];
        let stress = [];
        let discharge = [];

        const locationSelect = document.getElementById("locationSelect");
        locationSelect.innerHTML = "";

        data.locations.forEach((loc, index) => {
            const i = loc.indicators;

            names.push(loc.name);
            forecastRain.push(i.forecast_rainfall_total_mm || 0);
            historyRain.push(i.history_rainfall_total_mm || 0);
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
                    <td>${fmt(i.forecast_rainfall_total_mm)}</td>
                    <td>${fmt(i.history_rainfall_total_mm)}</td>
                    <td>${fmt(i.forecast_et0_total_mm)}</td>
                    <td>${fmt(i.history_mean_temperature_c)}</td>
                    <td>${fmt(i.river_discharge_peak_m3s)}</td>
                    <td>${badge(i.drought_risk)}</td>
                    <td>${badge(i.flood_risk)}</td>
                    <td>${fmt(i.water_stress_score_0_100)}</td>
                </tr>
            `;
        });

        rowsBox.innerHTML = rows;

        updateMap();
        drawSummaryCharts(names, forecastRain, historyRain, stress, discharge);
        drawTimeSeries();

        status.innerHTML = "Online data loaded successfully. Current API: " + url;
        status.className = "";

    } catch (error) {
        status.innerHTML = "Error loading dashboard data: " + error;
        status.className = "error";
        rowsBox.innerHTML = "<tr><td colspan='10'>Failed to load data</td></tr>";
    }
}

function drawSummaryCharts(names, forecastRain, historyRain, stress, discharge) {
    Plotly.newPlot("rainChart", [
        {
            x: names,
            y: forecastRain,
            type: "bar",
            name: "Forecast rainfall"
        },
        {
            x: names,
            y: historyRain,
            type: "bar",
            name: "Historical rainfall"
        }
    ], {
        title: "Rainfall by monitoring location",
        barmode: "group",
        yaxis: { title: "Rainfall, mm" }
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

    Plotly.newPlot("dischargeChart", [
        {
            x: names,
            y: discharge,
            type: "bar",
            name: "Peak discharge"
        }
    ], {
        title: "Peak river discharge by monitoring location",
        yaxis: { title: "m³/s" }
    }, {responsive: true});
}

function drawTimeSeries() {
    if (!latestData || !latestData.locations || latestData.locations.length === 0) return;

    const selectedIndex = document.getElementById("locationSelect").value || 0;
    const loc = latestData.locations[selectedIndex];

    Plotly.newPlot("historyRainChart", [
        {
            x: loc.history_timeseries.dates,
            y: loc.history_timeseries.rainfall_mm,
            type: "scatter",
            mode: "lines+markers",
            name: "Historical rainfall"
        },
        {
            x: loc.history_timeseries.dates,
            y: loc.history_timeseries.et0_mm,
            type: "scatter",
            mode: "lines+markers",
            name: "Historical ET0"
        }
    ], {
        title: "Historical rainfall and ET0: " + loc.name,
        yaxis: { title: "mm" }
    }, {responsive: true});

    Plotly.newPlot("forecastRainChart", [
        {
            x: loc.forecast_timeseries.dates,
            y: loc.forecast_timeseries.rainfall_mm,
            type: "scatter",
            mode: "lines+markers",
            name: "Forecast rainfall"
        },
        {
            x: loc.forecast_timeseries.dates,
            y: loc.forecast_timeseries.et0_mm,
            type: "scatter",
            mode: "lines+markers",
            name: "Forecast ET0"
        }
    ], {
        title: "Forecast rainfall and ET0: " + loc.name,
        yaxis: { title: "mm" }
    }, {responsive: true});

    Plotly.newPlot("floodLineChart", [
        {
            x: loc.flood_timeseries.dates,
            y: loc.flood_timeseries.river_discharge_m3s,
            type: "scatter",
            mode: "lines+markers",
            name: "River discharge"
        }
    ], {
        title: "Forecast river discharge: " + loc.name,
        yaxis: { title: "m³/s" }
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
