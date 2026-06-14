import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import asyncio
import httpx
import time
import math

app = FastAPI(
    title="Limpopo Transboundary Basin Digital Twin OMNI-Engine",
    version="6.1.0",
    description="Production-grade physical-digital twin integrating Open-Meteo climate data, GloFAS-based flood routing, maps and hydroclimate analytics."
)

# ============================================================
# CACHE
# ============================================================

CACHE = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


# ============================================================
# STRATEGIC NODES
# ============================================================

LOCATIONS = {
    "upper_limpopo": {
        "name": "Upper Limpopo Headwaters Corridor",
        "lat": -25.20,
        "lon": 26.90,
        "iso": "ZA/BW",
        "type": "Hydrological Generation",
        "dam_capacity_m3": 120000000,
        "base_pop": 45000
    },
    "gaborone_catchment": {
        "name": "Gaborone Strategic Reservoir Hub",
        "lat": -24.65,
        "lon": 25.91,
        "iso": "BW",
        "type": "Critical Infrastructure",
        "dam_capacity_m3": 141100000,
        "base_pop": 230000
    },
    "shashe_tributary": {
        "name": "Francistown / Shashe Sub-Basin",
        "lat": -21.17,
        "lon": 27.51,
        "iso": "BW/ZW",
        "type": "Sub-catchment Input",
        "dam_capacity_m3": 85000000,
        "base_pop": 95000
    },
    "olifants_confluence": {
        "name": "Olifants River Transboundary Node",
        "lat": -24.00,
        "lon": 31.50,
        "iso": "ZA/MZ",
        "type": "High Abstraction Pathway",
        "dam_capacity_m3": 2400000000,
        "base_pop": 620000
    },
    "beitbridge_gateway": {
        "name": "Beitbridge International Monitoring Station",
        "lat": -22.22,
        "lon": 30.00,
        "iso": "ZW/ZA",
        "type": "Diplomatic Verification Corridor",
        "dam_capacity_m3": 0,
        "base_pop": 120000
    },
    "massingir_dam": {
        "name": "Massingir Operational Control Framework",
        "lat": -23.88,
        "lon": 32.16,
        "iso": "MZ",
        "type": "Critical Infrastructure",
        "dam_capacity_m3": 2844000000,
        "base_pop": 35000
    },
    "chokwe_irrigation": {
        "name": "Chokwe Lowland Agricultural Delta",
        "lat": -24.53,
        "lon": 32.98,
        "iso": "MZ",
        "type": "LULC Abstraction Hub",
        "dam_capacity_m3": 0,
        "base_pop": 180000
    },
    "xai_xai_estuary": {
        "name": "Xai-Xai Discharge Terminal Mouth",
        "lat": -25.05,
        "lon": 33.65,
        "iso": "MZ",
        "type": "Estuary Outflow",
        "dam_capacity_m3": 0,
        "base_pop": 140000
    }
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def clean_numbers(values):
    if not values:
        return []
    return [
        value for value in values
        if isinstance(value, (int, float)) and not math.isnan(value)
    ]


def safe_sum(values):
    values = clean_numbers(values)
    return sum(values) if values else 0.0


def safe_mean(values):
    values = clean_numbers(values)
    return sum(values) / len(values) if values else 0.0


def safe_max(values):
    values = clean_numbers(values)
    return max(values) if values else 0.0


async def fetch_telemetry_async(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    param_key = str((url, tuple(sorted(params.items()))))
    now = time.time()

    if param_key in CACHE:
        cached_time, cached_data = CACHE[param_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_data

    try:
        response = await client.get(url, params=params, timeout=40.0)
        response.raise_for_status()
        data = response.json()
        CACHE[param_key] = (now, data)
        return data
    except Exception as error:
        return {
            "error": str(error),
            "url": url,
            "params": params
        }


def estimate_soil_saturation(rain_series, et0_series):
    """
    Soil moisture proxy.
    Open-Meteo daily forecast may not reliably return soil moisture as a daily variable everywhere,
    so this estimates saturation from short-term water balance.
    """
    rain_total = safe_sum(rain_series)
    et0_total = safe_sum(et0_series)
    balance = rain_total - et0_total

    if balance >= 40:
        return 0.42
    if balance >= 15:
        return 0.34
    if balance >= 0:
        return 0.28
    if balance >= -20:
        return 0.22
    if balance >= -50:
        return 0.16
    return 0.11


def calculate_derived_indices(rain_series, et0_series, discharge_series):
    antecedent_rain = safe_sum(rain_series)
    avg_rain = safe_mean(rain_series)
    avg_et0 = safe_mean(et0_series)
    climatic_water_balance = avg_rain - avg_et0
    current_soil_moisture = estimate_soil_saturation(rain_series, et0_series)
    peak_discharge = safe_max(discharge_series)

    if current_soil_moisture < 0.15 and climatic_water_balance < -2.0:
        drought_status = "Very High Risk"
    elif current_soil_moisture < 0.22 or climatic_water_balance < -0.5:
        drought_status = "Moderate Operational Deficit"
    else:
        drought_status = "Hydrologically Favorable"

    if peak_discharge >= 120.0:
        flood_status = "Critical Inundation Alert"
    elif peak_discharge >= 50.0:
        flood_status = "Active Downstream Routing Advisory"
    else:
        flood_status = "Safe Channel Baseline"

    return {
        "antecedent_rain_mm": round(antecedent_rain, 2),
        "climatic_water_balance_mm_day": round(climatic_water_balance, 2),
        "current_soil_saturation_m3_m3": round(current_soil_moisture, 3),
        "peak_discharge_m3_s": round(peak_discharge, 2),
        "drought_status": drought_status,
        "flood_status": flood_status
    }


# ============================================================
# API ROUTES
# ============================================================

@app.get("/api/locations")
def api_locations():
    return LOCATIONS


@app.get("/api/v6/twin-engine")
async def get_digital_twin_telemetry(
    cc_precip_modifier: float = Query(
        1.0,
        ge=0.5,
        le=2.0,
        description="Climate adaptation precipitation modifier"
    )
):
    today = date.today()
    hist_start = (today - timedelta(days=90)).isoformat()
    hist_end = (today - timedelta(days=1)).isoformat()

    async with httpx.AsyncClient() as client:
        tasks = []
        location_keys = list(LOCATIONS.keys())

        for key in location_keys:
            meta = LOCATIONS[key]

            weather_task = fetch_telemetry_async(
                client,
                "https://api.open-meteo.com/v1/forecast",
                {
                    "latitude": meta["lat"],
                    "longitude": meta["lon"],
                    "daily": "precipitation_sum,et0_fao_evapotranspiration",
                    "forecast_days": 16,
                    "timezone": "auto"
                }
            )

            archive_task = fetch_telemetry_async(
                client,
                "https://archive-api.open-meteo.com/v1/archive",
                {
                    "latitude": meta["lat"],
                    "longitude": meta["lon"],
                    "start_date": hist_start,
                    "end_date": hist_end,
                    "daily": "precipitation_sum",
                    "timezone": "auto"
                }
            )

            flood_task = fetch_telemetry_async(
                client,
                "https://flood-api.open-meteo.com/v1/flood",
                {
                    "latitude": meta["lat"],
                    "longitude": meta["lon"],
                    "daily": "river_discharge",
                    "forecast_days": 30,
                    "timezone": "auto"
                }
            )

            tasks.extend([weather_task, archive_task, flood_task])

        responses = await asyncio.gather(*tasks)

        compiled_twin_payload = []

        for index, key in enumerate(location_keys):
            meta = LOCATIONS[key]

            weather_data = responses[index * 3]
            archive_data = responses[index * 3 + 1]
            flood_data = responses[index * 3 + 2]

            raw_rain = weather_data.get("daily", {}).get("precipitation_sum", []) or []
            modified_rain = [
                round(value * cc_precip_modifier, 2)
                for value in clean_numbers(raw_rain)
            ]

            et0_series = weather_data.get("daily", {}).get("et0_fao_evapotranspiration", []) or []
            hist_rain = archive_data.get("daily", {}).get("precipitation_sum", []) or []
            discharge_series = flood_data.get("daily", {}).get("river_discharge", []) or []

            indices = calculate_derived_indices(hist_rain, et0_series, discharge_series)

            simulated_storage_pct = 100.0

            if meta["dam_capacity_m3"] > 0:
                inflow_factor = safe_sum(discharge_series) * 86400 if discharge_series else 500000
                simulated_storage_pct = min(
                    100.0,
                    max(
                        15.0,
                        ((inflow_factor / meta["dam_capacity_m3"]) * 100.0) * cc_precip_modifier
                    )
                )

            population_exposure = 0

            if indices["peak_discharge_m3_s"] > 60.0:
                population_exposure = int(
                    meta["base_pop"] * (indices["peak_discharge_m3_s"] / 190.0)
                )
                population_exposure = min(population_exposure, meta["base_pop"])

            compiled_twin_payload.append({
                "id": key,
                "name": meta["name"],
                "iso": meta["iso"],
                "type": meta["type"],
                "coordinates": {
                    "lat": meta["lat"],
                    "lon": meta["lon"]
                },
                "telemetry_indices": indices,
                "infrastructural_layer": {
                    "has_reservoir": meta["dam_capacity_m3"] > 0,
                    "max_design_capacity_m3": meta["dam_capacity_m3"],
                    "computed_storage_volume_pct": round(simulated_storage_pct, 1)
                },
                "human_vulnerability_layer": {
                    "base_population": meta["base_pop"],
                    "computed_population_at_risk": population_exposure
                },
                "time_series_vectors": {
                    "forecast_dates": weather_data.get("daily", {}).get("time", []),
                    "modified_forecast_precipitation_mm": modified_rain,
                    "forecast_evapotranspiration_mm": et0_series,
                    "flood_dates": flood_data.get("daily", {}).get("time", []),
                    "discharge_curve_m3_s": discharge_series
                },
                "raw_errors": {
                    "weather_error": weather_data.get("error"),
                    "archive_error": archive_data.get("error"),
                    "flood_error": flood_data.get("error")
                }
            })

        total_population_at_risk = sum(
            item["human_vulnerability_layer"]["computed_population_at_risk"]
            for item in compiled_twin_payload
        )

        mean_soil = safe_mean([
            item["telemetry_indices"]["current_soil_saturation_m3_m3"]
            for item in compiled_twin_payload
        ])

        return {
            "twin_meta": {
                "basin": "Limpopo Transboundary River Basin Grid Matrix",
                "execution_timestamp": time.time(),
                "active_scenario_modifier": cc_precip_modifier
            },
            "macro_basin_indicators": {
                "aggregate_population_at_risk": total_population_at_risk,
                "mean_basin_soil_saturation_m3_m3": round(mean_soil, 3)
            },
            "nodes": compiled_twin_payload
        }


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/", response_class=HTMLResponse)
def stream_dashboard_ui():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Limpopo Transboundary River Basin Digital Twin OMNI-Dashboard</title>

    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <style>
        :root {
            --slate-900: #0f172a;
            --teal-600: #0d9488;
            --emerald-600: #10b981;
            --amber-500: #f59e0b;
            --rose-600: #e11d48;
            --orange-500: #f97316;
            --gray-500: #64748b;
        }

        body {
            font-family: Inter, Arial, sans-serif;
            margin: 0;
            background: #f8fafc;
            color: #1e293b;
        }

        .hero {
            background: linear-gradient(135deg, #0f172a, #111827, #134e4a);
            color: white;
            padding: 25px 40px;
            border-bottom: 4px solid var(--teal-600);
        }

        .hero h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -0.05em;
        }

        .hero p {
            margin: 5px 0 0 0;
            color: #94a3b8;
            font-size: 14px;
        }

        .wrapper {
            display: flex;
            flex-direction: row;
            min-height: calc(100vh - 90px);
        }

        .control-panel {
            width: 350px;
            background: white;
            border-right: 1px solid #e2e8f0;
            padding: 20px;
            box-sizing: border-box;
            flex-shrink: 0;
        }

        .workspace {
            flex-grow: 1;
            padding: 25px;
            box-sizing: border-box;
            overflow-y: auto;
        }

        .grid-layout {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }

        .card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05),
                        0 2px 4px -1px rgba(0,0,0,0.03);
            border: 1px solid #f1f5f9;
        }

        .control-group {
            margin-bottom: 20px;
        }

        label {
            font-size: 12px;
            font-weight: 700;
            color: #475569;
            display: block;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .slider-output {
            font-weight: 800;
            color: var(--teal-600);
            float: right;
            font-size: 14px;
        }

        .btn-action {
            width: 100%;
            background: var(--slate-900);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 8px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-action:hover {
            background: #334155;
        }

        select {
            width: 100%;
            padding: 10px;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
            font-weight: 600;
        }

        #map {
            height: 430px;
            width: 100%;
            border-radius: 12px;
            border: 1px solid #e2e8f0;
            margin-bottom: 25px;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.06);
        }

        .metric-display {
            font-size: 28px;
            font-weight: 900;
            color: var(--slate-900);
            margin-top: 5px;
            letter-spacing: -0.03em;
        }

        .metric-desc {
            color: #64748b;
            font-size: 12px;
            margin-top: 2px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 13px;
        }

        th, td {
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }

        th {
            background: #f8fafc;
            font-weight: 700;
            color: #475569;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.05em;
        }

        .status-badge {
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            color: white;
            display: inline-block;
        }

        .Low {
            background: var(--emerald-600);
        }

        .Moderate {
            background: var(--amber-500);
        }

        .High {
            background: var(--orange-500);
        }

        .Veryhigh {
            background: var(--rose-600);
        }

        .Unknown {
            background: var(--gray-500);
        }

        .loading {
            color: #2563eb;
            font-weight: 700;
            font-size: 13px;
        }

        .error {
            color: var(--rose-600);
            font-weight: 700;
            font-size: 13px;
        }

        .diplomacy-banner {
            background: #fff7ed;
            border-left: 4px solid var(--amber-500);
            padding: 14px;
            border-radius: 8px;
            font-size: 13px;
            color: #c2410c;
            font-weight: 500;
            margin-bottom: 20px;
        }

        .legend-ui {
            background: white;
            padding: 12px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
            box-shadow: 0 4px 10px rgba(0,0,0,0.08);
            line-height: 20px;
        }

        .legend-ui span {
            display: inline-block;
            width: 12px;
            height: 12px;
            margin-right: 6px;
            border-radius: 50%;
            vertical-align: middle;
        }

        .api-box {
            background: #0f172a;
            color: #e2e8f0;
            border-radius: 10px;
            padding: 12px;
            font-size: 12px;
            max-height: 350px;
            overflow: auto;
            margin-top: 20px;
        }

        @media (max-width: 900px) {
            .wrapper {
                flex-direction: column;
            }

            .control-panel {
                width: 100%;
                border-right: none;
                border-bottom: 1px solid #e2e8f0;
            }
        }
    </style>
</head>

<body>
    <div class="hero">
        <h1>Limpopo Transboundary River Basin Digital Twin OMNI-Engine</h1>
        <p>Telemetry processing, flood routing, soil-water proxy, reservoir stress and population exposure dashboard</p>
    </div>

    <div class="wrapper">
        <div class="control-panel">
            <div class="control-group">
                <label>
                    Climate Adaptation Simulation Factor
                    <span class="slider-output" id="ccSliderDisplay">1.0x</span>
                </label>

                <input
                    type="range"
                    id="ccModifierSlider"
                    min="0.5"
                    max="2.0"
                    step="0.1"
                    value="1.0"
                    style="width:100%; accent-color:var(--teal-600);"
                    oninput="updateSliderText(this.value)"
                >

                <small style="color:#64748b; font-size:11px; display:block; margin-top:4px;">
                    Modifies precipitation volume coefficients across the monitoring nodes.
                </small>
            </div>

            <div class="control-group">
                <label>Geospatial Map View Mode</label>

                <select id="mapVariableSelector" onchange="executeMapVariableRerender()">
                    <option value="discharge">River discharge routing, m³/s</option>
                    <option value="reservoir">Dam reservoir capacity, %</option>
                    <option value="soil">Soil saturation proxy, m³/m³</option>
                    <option value="vulnerability">Population at risk</option>
                </select>
            </div>

            <button class="btn-action" onclick="synchronizeTwinExecutionState()">
                Re-Compute Digital Twin State
            </button>

            <p id="status" class="loading" style="margin-top:15px;">
                Initializing digital twin telemetry...
            </p>

            <div style="margin-top:25px; border-top:1px dashed #e2e8f0; padding-top:20px;">
                <label style="color:var(--teal-600);">Transboundary Water Ledger</label>

                <div class="diplomacy-banner">
                    <strong>Downstream Flow Integrity Flag:</strong>
                    Cross-border flow metrics from South Africa / Zimbabwe into Mozambique are tracked for operational planning.
                </div>
            </div>

            <div class="api-box" id="apiPreview">
                API response will appear here after synchronization.
            </div>
        </div>

        <div class="workspace">
            <div class="grid-layout">
                <div class="card" style="border-top:4px solid var(--rose-600);">
                    <label>Basin Population Exposed at Risk</label>
                    <div class="metric-display" id="basinParMetric">---</div>
                    <div class="metric-desc">Computed exposure intersecting discharge risk and population node weight</div>
                </div>

                <div class="card" style="border-top:4px solid var(--teal-600);">
                    <label>Basin Average Soil Moisture Proxy</label>
                    <div class="metric-display" id="basinSoilMetric">---</div>
                    <div class="metric-desc">Estimated m³/m³ from precipitation and ET0 balance</div>
                </div>
            </div>

            <div id="map"></div>

            <div class="card" style="margin-bottom:25px; overflow-x:auto;">
                <h3 style="margin:0 0 15px 0; font-size:16px; font-weight:800; letter-spacing:-0.02em;">
                    Digital Twin Real-Time State Logging Matrix
                </h3>

                <table>
                    <thead>
                        <tr>
                            <th>Gauge Node Anchor</th>
                            <th>Riparian Domain</th>
                            <th>Antecedent 90d Rain</th>
                            <th>Simulated Flow</th>
                            <th>Dam Levels</th>
                            <th>Soil Proxy</th>
                            <th>Drought Status</th>
                            <th>Flood Hazard</th>
                            <th>Population at Risk</th>
                        </tr>
                    </thead>

                    <tbody id="twinMatrixTableBody">
                        <tr>
                            <td colspan="9" style="color:#64748b; text-align:center;">
                                Synchronizing telemetry processing strings...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="grid-layout" style="grid-template-columns: 1fr;">
                <div class="card"><div id="multiTemporalHydrograph"></div></div>
                <div class="card"><div id="dischargeRoutingGraph"></div></div>
                <div class="card"><div id="nodeComparisonGraph"></div></div>
            </div>
        </div>
    </div>

    <script>
        let map;
        let mapMarkerLayerGroup;
        let twinGlobalPayloadState = null;

        const polylineCorridorCoordinates = [
            [-25.20, 26.90],
            [-24.65, 25.91],
            [-21.17, 27.51],
            [-22.22, 30.00],
            [-24.00, 31.50],
            [-23.88, 32.16],
            [-24.53, 32.98],
            [-25.05, 33.65]
        ];

        function updateSliderText(value) {
            document.getElementById("ccSliderDisplay").textContent = value + "x";
        }

        function initializeGeospatialTwinMap() {
            map = L.map("map", {zoomControl: true}).setView([-23.8, 30.2], 6);

            const standardBasemap = L.tileLayer(
                "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                {
                    attribution: "OpenStreetMap contributors"
                }
            ).addTo(map);

            const topoBasemap = L.tileLayer(
                "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                {
                    maxZoom: 17,
                    attribution: "OpenTopoMap contributors"
                }
            );

            L.control.layers({
                "Standard Hydro-Met Baseline": standardBasemap,
                "Topographic Profile Map View": topoBasemap
            }).addTo(map);

            mapMarkerLayerGroup = L.layerGroup().addTo(map);

            L.polyline(polylineCorridorCoordinates, {
                color: "#0284c7",
                weight: 4,
                opacity: 0.7,
                dashArray: "4, 8"
            }).addTo(map).bindPopup("Approximate Limpopo monitoring corridor");

            const legendControl = L.control({position: "bottomright"});

            legendControl.onAdd = function() {
                const div = L.DomUtil.create("div", "legend-ui");

                div.innerHTML = `
                    <strong>Twin Matrix Intensity</strong><br>
                    <span style="background:#10b981"></span> Hydro-compliant threshold<br>
                    <span style="background:#f59e0b"></span> Moderate deviation<br>
                    <span style="background:#e11d48"></span> Critical hazard
                `;

                return div;
            };

            legendControl.addTo(map);
        }

        function evaluateColorScaleProfile(value, maxValue, invert=false) {
            const ratio = maxValue <= 0 ? 0 : value / maxValue;

            if (!invert) {
                if (ratio >= 0.75) return "#e11d48";
                if (ratio >= 0.40) return "#f59e0b";
                return "#10b981";
            }

            if (ratio <= 0.35) return "#e11d48";
            if (ratio <= 0.60) return "#f59e0b";
            return "#10b981";
        }

        function executeMapVariableRerender() {
            if (!twinGlobalPayloadState || !mapMarkerLayerGroup) return;

            mapMarkerLayerGroup.clearLayers();

            const targetViewMode = document.getElementById("mapVariableSelector").value;

            const absoluteValueMatrix = twinGlobalPayloadState.nodes.map(node => {
                if (targetViewMode === "discharge") return node.telemetry_indices.peak_discharge_m3_s;
                if (targetViewMode === "reservoir") return node.infrastructural_layer.computed_storage_volume_pct;
                if (targetViewMode === "soil") return node.telemetry_indices.current_soil_saturation_m3_m3;
                return node.human_vulnerability_layer.computed_population_at_risk;
            });

            const maximumValueCap = Math.max(...absoluteValueMatrix, 1);
            const bounds = [];

            twinGlobalPayloadState.nodes.forEach(node => {
                let trackingValue = 0;
                let isInvertedScale = false;

                if (targetViewMode === "discharge") {
                    trackingValue = node.telemetry_indices.peak_discharge_m3_s;
                } else if (targetViewMode === "reservoir") {
                    trackingValue = node.infrastructural_layer.computed_storage_volume_pct;
                    isInvertedScale = true;
                } else if (targetViewMode === "soil") {
                    trackingValue = node.telemetry_indices.current_soil_saturation_m3_m3;
                    isInvertedScale = true;
                } else {
                    trackingValue = node.human_vulnerability_layer.computed_population_at_risk;
                }

                const nodeColorHex = evaluateColorScaleProfile(
                    trackingValue,
                    maximumValueCap,
                    isInvertedScale
                );

                const radiusSize = 11 + (30 * (trackingValue / maximumValueCap));

                const marker = L.circleMarker(
                    [node.coordinates.lat, node.coordinates.lon],
                    {
                        radius: radiusSize,
                        color: nodeColorHex,
                        fillColor: nodeColorHex,
                        fillOpacity: 0.62,
                        weight: 2
                    }
                ).addTo(mapMarkerLayerGroup);

                const earthObservationUrl =
                    `https://browser.dataspace.copernicus.eu/?zoom=11&lat=${node.coordinates.lat}&lng=${node.coordinates.lon}`;

                marker.bindPopup(`
                    <strong style='font-size:13px;'>${node.name}</strong><br>
                    <small style='color:#64748b;'>Domain: ${node.iso} | ${node.type}</small><br>
                    <hr style='border:0; border-top:1px solid #e2e8f0; margin:6px 0;'>
                    <b>Discharge:</b> ${node.telemetry_indices.peak_discharge_m3_s} m³/s<br>
                    <b>Reservoir level:</b> ${node.infrastructural_layer.has_reservoir ? node.infrastructural_layer.computed_storage_volume_pct + "%" : "No reservoir"}<br>
                    <b>Soil saturation proxy:</b> ${node.telemetry_indices.current_soil_saturation_m3_m3} m³/m³<br>
                    <b>Population at risk:</b> ${node.human_vulnerability_layer.computed_population_at_risk.toLocaleString()}<br>
                    <b>Drought status:</b> ${node.telemetry_indices.drought_status}<br>
                    <b>Flood status:</b> ${node.telemetry_indices.flood_status}<br>
                    <hr style='border:0; border-top:1px solid #e2e8f0; margin:6px 0;'>
                    <a href="${earthObservationUrl}" target="_blank" style="font-weight:700; color:#0d9488; text-decoration:none;">
                        Open Copernicus Browser
                    </a>
                `);

                bounds.push([node.coordinates.lat, node.coordinates.lon]);
            });

            if (bounds.length > 0) {
                map.fitBounds(bounds, {padding: [40, 40]});
            }
        }

        function statusClassForDrought(text) {
            if (text.includes("Very High")) return "Veryhigh";
            if (text.includes("Moderate")) return "Moderate";
            return "Low";
        }

        function statusClassForFlood(text) {
            if (text.includes("Critical")) return "Veryhigh";
            if (text.includes("Advisory")) return "Moderate";
            return "Low";
        }

        async function synchronizeTwinExecutionState() {
            const statusDisplay = document.getElementById("status");
            const matrixTableBody = document.getElementById("twinMatrixTableBody");

            statusDisplay.textContent = "Querying online telemetry arrays from Open-Meteo and GloFAS-based flood API...";
            statusDisplay.className = "loading";

            matrixTableBody.innerHTML = `
                <tr>
                    <td colspan="9" style="color:#64748b; text-align:center;">
                        Loading live digital twin state...
                    </td>
                </tr>
            `;

            const activeCcFactor = document.getElementById("ccModifierSlider").value;

            try {
                const response = await fetch(`/api/v6/twin-engine?cc_precip_modifier=${activeCcFactor}`);
                const payload = await response.json();

                twinGlobalPayloadState = payload;

                document.getElementById("apiPreview").textContent =
                    JSON.stringify(payload, null, 2).slice(0, 6000);

                document.getElementById("basinParMetric").textContent =
                    payload.macro_basin_indicators.aggregate_population_at_risk.toLocaleString() + " people";

                document.getElementById("basinSoilMetric").textContent =
                    payload.macro_basin_indicators.mean_basin_soil_saturation_m3_m3 + " m³/m³";

                let html = "";

                payload.nodes.forEach(node => {
                    const droughtClass = statusClassForDrought(node.telemetry_indices.drought_status);
                    const floodClass = statusClassForFlood(node.telemetry_indices.flood_status);

                    html += `
                        <tr>
                            <td><strong>${node.name}</strong></td>
                            <td><small style='font-weight:700; color:#475569;'>${node.iso}</small></td>
                            <td>${node.telemetry_indices.antecedent_rain_mm} mm</td>
                            <td><strong>${node.telemetry_indices.peak_discharge_m3_s} m³/s</strong></td>
                            <td>${node.infrastructural_layer.has_reservoir ? node.infrastructural_layer.computed_storage_volume_pct + "%" : "<span style='color:#cbd5e1;'>N/A</span>"}</td>
                            <td>${node.telemetry_indices.current_soil_saturation_m3_m3}</td>
                            <td><span class="status-badge ${droughtClass}">${node.telemetry_indices.drought_status}</span></td>
                            <td><span class="status-badge ${floodClass}">${node.telemetry_indices.flood_status}</span></td>
                            <td><strong style='color:${node.human_vulnerability_layer.computed_population_at_risk > 0 ? "var(--rose-600)" : "var(--slate-900)"};'>
                                ${node.human_vulnerability_layer.computed_population_at_risk.toLocaleString()}
                            </strong></td>
                        </tr>
                    `;
                });

                matrixTableBody.innerHTML = html;

                executeMapVariableRerender();
                generateAdvancedPlotlyAnalytics();

                statusDisplay.textContent = "Twin state synchronized successfully.";
                statusDisplay.className = "";

            } catch (error) {
                statusDisplay.textContent = "Twin execution interrupted: " + error;
                statusDisplay.className = "error";

                matrixTableBody.innerHTML = `
                    <tr>
                        <td colspan="9" style="color:#e11d48; text-align:center;">
                            Failed to load telemetry data.
                        </td>
                    </tr>
                `;
            }
        }

        function generateAdvancedPlotlyAnalytics() {
            if (!twinGlobalPayloadState || twinGlobalPayloadState.nodes.length === 0) return;

            const defaultNode = twinGlobalPayloadState.nodes[0];

            const layout = {
                paper_bgcolor: "white",
                plot_bgcolor: "white",
                font: {
                    family: "Inter, Arial, sans-serif",
                    color: "#0f172a"
                },
                margin: {
                    l: 60,
                    r: 30,
                    t: 55,
                    b: 55
                },
                xaxis: {gridcolor: "#f1f5f9"},
                yaxis: {gridcolor: "#f1f5f9"}
            };

            Plotly.newPlot("multiTemporalHydrograph", [
                {
                    x: defaultNode.time_series_vectors.forecast_dates,
                    y: defaultNode.time_series_vectors.modified_forecast_precipitation_mm,
                    type: "scatter",
                    mode: "lines+markers",
                    name: "Scenario precipitation",
                    line: {color: "#0ea5e9", width: 2.5}
                },
                {
                    x: defaultNode.time_series_vectors.forecast_dates,
                    y: defaultNode.time_series_vectors.forecast_evapotranspiration_mm,
                    type: "scatter",
                    mode: "lines",
                    name: "ET0 demand",
                    line: {color: "#ef4444", width: 2}
                }
            ], {
                ...layout,
                title: `Mass Balance Projection: ${defaultNode.name}`,
                yaxis: {title: "mm/day"}
            }, {responsive: true});

            Plotly.newPlot("dischargeRoutingGraph", [
                {
                    x: defaultNode.time_series_vectors.flood_dates,
                    y: defaultNode.time_series_vectors.discharge_curve_m3_s,
                    type: "scatter",
                    mode: "lines",
                    fill: "tozeroy",
                    name: "Discharge hydrograph",
                    line: {color: "#0d9488", width: 3}
                }
            ], {
                ...layout,
                title: `30-Day Channel Discharge Routing: ${defaultNode.name}`,
                yaxis: {title: "m³/s"}
            }, {responsive: true});

            const nodeNames = twinGlobalPayloadState.nodes.map(node => node.name);
            const dischargeValues = twinGlobalPayloadState.nodes.map(node => node.telemetry_indices.peak_discharge_m3_s);
            const soilValues = twinGlobalPayloadState.nodes.map(node => node.telemetry_indices.current_soil_saturation_m3_m3);
            const populationValues = twinGlobalPayloadState.nodes.map(node => node.human_vulnerability_layer.computed_population_at_risk);

            Plotly.newPlot("nodeComparisonGraph", [
                {
                    x: nodeNames,
                    y: dischargeValues,
                    type: "bar",
                    name: "Peak discharge",
                    marker: {color: "#0d9488"}
                },
                {
                    x: nodeNames,
                    y: populationValues,
                    type: "bar",
                    name: "Population at risk",
                    marker: {color: "#e11d48"},
                    yaxis: "y2"
                }
            ], {
                ...layout,
                title: "Node Comparison: Discharge and Population Exposure",
                yaxis: {title: "Discharge, m³/s"},
                yaxis2: {
                    title: "Population at risk",
                    overlaying: "y",
                    side: "right"
                },
                legend: {orientation: "h"},
                margin: {
                    l: 60,
                    r: 70,
                    t: 55,
                    b: 140
                }
            }, {responsive: true});
        }

        function setDefaultDates() {
            // Compatibility function for older dashboard versions.
            return;
        }

        window.onload = function() {
            initializeGeospatialTwinMap();
            setDefaultDates();
            synchronizeTwinExecutionState();
        };
    </script>
</body>
</html>
    """


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
              
