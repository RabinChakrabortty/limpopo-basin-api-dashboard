import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from datetime import date, timedelta
import asyncio
import httpx
import time
import math
from collections import defaultdict


app = FastAPI(
    title="Limpopo Basin Maximum-Factor Digital Twin",
    version="8.0.0",
    description="Maximum-factor online hydroclimate, flood, drought, LULC, population, reservoir, infrastructure and prediction dashboard for the Limpopo River Basin."
)

CACHE = {}
CACHE_TTL_SECONDS = 6 * 60 * 60


LOCATIONS = {
    "upper_limpopo": {
        "name": "Upper Limpopo Headwaters Corridor",
        "lat": -25.20,
        "lon": 26.90,
        "iso": "ZA/BW",
        "country": "South Africa / Botswana",
        "type": "Headwater runoff generation zone",
        "population": 45000,
        "dam_capacity_m3": 120000000,
        "irrigation_pressure": 42,
        "urban_pressure": 18,
        "groundwater_dependency": 64,
        "ecosystem_sensitivity": 66,
        "lulc": {"urban": 6, "cropland": 28, "grassland": 42, "forest": 8, "water": 2, "bare": 14}
    },
    "gaborone_catchment": {
        "name": "Gaborone Strategic Reservoir Hub",
        "lat": -24.65,
        "lon": 25.91,
        "iso": "BW",
        "country": "Botswana",
        "type": "Urban water supply and reservoir node",
        "population": 230000,
        "dam_capacity_m3": 141100000,
        "irrigation_pressure": 30,
        "urban_pressure": 82,
        "groundwater_dependency": 72,
        "ecosystem_sensitivity": 54,
        "lulc": {"urban": 24, "cropland": 12, "grassland": 38, "forest": 4, "water": 3, "bare": 19}
    },
    "shashe_tributary": {
        "name": "Francistown / Shashe Sub-Basin",
        "lat": -21.17,
        "lon": 27.51,
        "iso": "BW/ZW",
        "country": "Botswana / Zimbabwe",
        "type": "Ephemeral tributary and storage zone",
        "population": 95000,
        "dam_capacity_m3": 85000000,
        "irrigation_pressure": 38,
        "urban_pressure": 46,
        "groundwater_dependency": 70,
        "ecosystem_sensitivity": 59,
        "lulc": {"urban": 12, "cropland": 18, "grassland": 44, "forest": 5, "water": 2, "bare": 19}
    },
    "polokwane_platform": {
        "name": "Polokwane Regional Platform",
        "lat": -23.90,
        "lon": 29.45,
        "iso": "ZA",
        "country": "South Africa",
        "type": "Urban, mining and groundwater abstraction zone",
        "population": 510000,
        "dam_capacity_m3": 0,
        "irrigation_pressure": 48,
        "urban_pressure": 78,
        "groundwater_dependency": 84,
        "ecosystem_sensitivity": 62,
        "lulc": {"urban": 22, "cropland": 30, "grassland": 28, "forest": 5, "water": 1, "bare": 14}
    },
    "mokopane_mogalakwena": {
        "name": "Mokopane / Mogalakwena System",
        "lat": -24.19,
        "lon": 29.01,
        "iso": "ZA",
        "country": "South Africa",
        "type": "Mining, agriculture and dryland abstraction zone",
        "population": 185000,
        "dam_capacity_m3": 0,
        "irrigation_pressure": 52,
        "urban_pressure": 50,
        "groundwater_dependency": 78,
        "ecosystem_sensitivity": 60,
        "lulc": {"urban": 10, "cropland": 36, "grassland": 32, "forest": 5, "water": 1, "bare": 16}
    },
    "beitbridge_gateway": {
        "name": "Beitbridge International Monitoring Station",
        "lat": -22.22,
        "lon": 30.00,
        "iso": "ZW/ZA",
        "country": "Zimbabwe / South Africa",
        "type": "Transboundary flow verification corridor",
        "population": 120000,
        "dam_capacity_m3": 0,
        "irrigation_pressure": 40,
        "urban_pressure": 40,
        "groundwater_dependency": 68,
        "ecosystem_sensitivity": 58,
        "lulc": {"urban": 8, "cropland": 20, "grassland": 40, "forest": 4, "water": 1, "bare": 27}
    },
    "olifants_confluence": {
        "name": "Olifants River Transboundary Node",
        "lat": -24.00,
        "lon": 31.50,
        "iso": "ZA/MZ",
        "country": "South Africa / Mozambique",
        "type": "High abstraction and tributary inflow pathway",
        "population": 620000,
        "dam_capacity_m3": 2400000000,
        "irrigation_pressure": 72,
        "urban_pressure": 48,
        "groundwater_dependency": 65,
        "ecosystem_sensitivity": 82,
        "lulc": {"urban": 10, "cropland": 34, "grassland": 24, "forest": 12, "water": 4, "bare": 16}
    },
    "massingir_dam": {
        "name": "Massingir Operational Control Framework",
        "lat": -23.88,
        "lon": 32.16,
        "iso": "MZ",
        "country": "Mozambique",
        "type": "Major downstream reservoir control zone",
        "population": 35000,
        "dam_capacity_m3": 2844000000,
        "irrigation_pressure": 55,
        "urban_pressure": 20,
        "groundwater_dependency": 44,
        "ecosystem_sensitivity": 86,
        "lulc": {"urban": 4, "cropland": 18, "grassland": 31, "forest": 18, "water": 12, "bare": 17}
    },
    "chokwe_irrigation": {
        "name": "Chokwe Lowland Agricultural Delta",
        "lat": -24.53,
        "lon": 32.98,
        "iso": "MZ",
        "country": "Mozambique",
        "type": "Irrigated agriculture and floodplain zone",
        "population": 180000,
        "dam_capacity_m3": 0,
        "irrigation_pressure": 92,
        "urban_pressure": 34,
        "groundwater_dependency": 52,
        "ecosystem_sensitivity": 76,
        "lulc": {"urban": 7, "cropland": 58, "grassland": 16, "forest": 5, "water": 5, "bare": 9}
    },
    "xai_xai_estuary": {
        "name": "Xai-Xai Discharge Terminal Mouth",
        "lat": -25.05,
        "lon": 33.65,
        "iso": "MZ",
        "country": "Mozambique",
        "type": "Estuary, coastal discharge and salinity-sensitive zone",
        "population": 140000,
        "dam_capacity_m3": 0,
        "irrigation_pressure": 50,
        "urban_pressure": 58,
        "groundwater_dependency": 48,
        "ecosystem_sensitivity": 94,
        "lulc": {"urban": 14, "cropland": 32, "grassland": 16, "forest": 10, "water": 14, "bare": 14}
    }
}


def clean_numbers(values):
    if not values:
        return []
    return [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]


def safe_sum(values):
    values = clean_numbers(values)
    return round(sum(values), 2) if values else 0.0


def safe_mean(values):
    values = clean_numbers(values)
    return round(sum(values) / len(values), 2) if values else 0.0


def safe_max(values):
    values = clean_numbers(values)
    return round(max(values), 2) if values else 0.0


def safe_min(values):
    values = clean_numbers(values)
    return round(min(values), 2) if values else 0.0


def clamp(value, low, high):
    return max(low, min(high, value))


async def fetch_json(client, url, params):
    key = str((url, tuple(sorted(params.items()))))
    now = time.time()

    if key in CACHE:
        created, data = CACHE[key]
        if now - created < CACHE_TTL_SECONDS:
            return data

    try:
        response = await client.get(url, params=params, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        CACHE[key] = (now, data)
        return data
    except Exception as error:
        return {"error": str(error), "url": url, "params": params}


def score_from_class(label):
    return {"Low": 20, "Moderate": 50, "High": 75, "Very high": 95}.get(label, 0)


def class_from_score(score):
    if score >= 80:
        return "Very high"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Moderate"
    return "Low"


def estimate_soil_saturation(rain, et0):
    rain_total = safe_sum(rain)
    et0_total = safe_sum(et0)
    balance = rain_total - et0_total

    if balance >= 60:
        return 0.45
    if balance >= 30:
        return 0.39
    if balance >= 10:
        return 0.33
    if balance >= 0:
        return 0.28
    if balance >= -25:
        return 0.22
    if balance >= -60:
        return 0.16
    return 0.10


def drought_risk_class(soil, water_balance_day, recent_90d_rain):
    risk = 0

    if soil < 0.14:
        risk += 45
    elif soil < 0.22:
        risk += 32
    elif soil < 0.30:
        risk += 18

    if water_balance_day < -3:
        risk += 35
    elif water_balance_day < -1:
        risk += 25
    elif water_balance_day < 0:
        risk += 12

    if recent_90d_rain < 45:
        risk += 20
    elif recent_90d_rain < 90:
        risk += 12

    return class_from_score(clamp(risk, 0, 100))


def flood_risk_class(peak_discharge):
    if peak_discharge >= 120:
        return "Very high"
    if peak_discharge >= 50:
        return "High"
    if peak_discharge >= 20:
        return "Moderate"
    return "Low"


def climate_risk_score(rain_total, et0_total, temp_max, wind_max, radiation_total):
    water_balance = rain_total - et0_total
    score = 0

    if water_balance < -80:
        score += 35
    elif water_balance < -40:
        score += 25
    elif water_balance < 0:
        score += 12

    if temp_max >= 42:
        score += 25
    elif temp_max >= 38:
        score += 18
    elif temp_max >= 34:
        score += 10

    if wind_max >= 45:
        score += 15
    elif wind_max >= 30:
        score += 8

    if radiation_total >= 180:
        score += 15
    elif radiation_total >= 120:
        score += 8

    return round(clamp(score, 0, 100), 2)


def lulc_pressure_score(lulc, irrigation_pressure, urban_pressure, ecosystem_sensitivity):
    urban = lulc.get("urban", 0)
    crop = lulc.get("cropland", 0)
    bare = lulc.get("bare", 0)
    forest = lulc.get("forest", 0)
    water = lulc.get("water", 0)

    score = (
        urban * 0.45 +
        crop * 0.35 +
        bare * 0.28 -
        forest * 0.18 -
        water * 0.08 +
        irrigation_pressure * 0.18 +
        urban_pressure * 0.16 +
        ecosystem_sensitivity * 0.10
    )

    return round(clamp(score, 0, 100), 2)


def reservoir_storage_percent(capacity, discharge, precip_modifier):
    if capacity <= 0:
        return None

    estimated_inflow_volume = safe_sum(discharge) * 86400
    storage = ((estimated_inflow_volume / capacity) * 100.0) * precip_modifier
    return round(clamp(storage, 8, 100), 1)


def reservoir_stress_score(storage_percent, groundwater_dependency):
    if storage_percent is None:
        return round(groundwater_dependency * 0.45, 2)

    score = 100 - storage_percent
    score = score * 0.75 + groundwater_dependency * 0.25
    return round(clamp(score, 0, 100), 2)


def population_exposure(population, flood_score, drought_score, lulc_score, climate_score):
    exposure_percent = (
        flood_score * 0.34 +
        drought_score * 0.26 +
        lulc_score * 0.20 +
        climate_score * 0.20
    )
    exposure_percent = clamp(exposure_percent, 0, 100)
    return int(population * exposure_percent / 100), round(exposure_percent, 2)


def build_climatology_prediction_from_history(history_daily, prediction_days):
    prediction_days = clamp(int(prediction_days), 1, 365)

    dates = history_daily.get("time", []) or []
    rain = history_daily.get("precipitation_sum", []) or []
    temp = history_daily.get("temperature_2m_mean", []) or []
    et0 = history_daily.get("et0_fao_evapotranspiration", []) or []

    by_day = defaultdict(lambda: {"rain": [], "temp": [], "et0": []})

    for i, d in enumerate(dates):
        try:
            key = d[5:10]
            if i < len(rain) and isinstance(rain[i], (int, float)):
                by_day[key]["rain"].append(rain[i])
            if i < len(temp) and isinstance(temp[i], (int, float)):
                by_day[key]["temp"].append(temp[i])
            if i < len(et0) and isinstance(et0[i], (int, float)):
                by_day[key]["et0"].append(et0[i])
        except Exception:
            continue

    fallback_rain = safe_mean(rain)
    fallback_temp = safe_mean(temp)
    fallback_et0 = safe_mean(et0)

    future_dates = []
    pred_rain = []
    pred_temp = []
    pred_et0 = []
    pred_balance = []

    tomorrow = date.today() + timedelta(days=1)

    for offset in range(prediction_days):
        future_day = tomorrow + timedelta(days=offset)
        key = future_day.isoformat()[5:10]

        r = safe_mean(by_day[key]["rain"]) or fallback_rain
        t = safe_mean(by_day[key]["temp"]) or fallback_temp
        e = safe_mean(by_day[key]["et0"]) or fallback_et0

        future_dates.append(future_day.isoformat())
        pred_rain.append(round(r, 2))
        pred_temp.append(round(t, 2))
        pred_et0.append(round(e, 2))
        pred_balance.append(round(r - e, 2))

    return {
        "dates": future_dates,
        "predicted_rainfall_mm": pred_rain,
        "predicted_temperature_c": pred_temp,
        "predicted_et0_mm": pred_et0,
        "predicted_water_balance_mm": pred_balance,
        "predicted_total_rainfall_mm": safe_sum(pred_rain),
        "predicted_total_et0_mm": safe_sum(pred_et0),
        "predicted_total_water_balance_mm": round(safe_sum(pred_rain) - safe_sum(pred_et0), 2),
        "predicted_mean_temperature_c": safe_mean(pred_temp)
    }


@app.get("/api/locations")
def api_locations():
    return LOCATIONS


@app.get("/api/v8/max-factors")
async def api_v8_max_factors(
    precip_modifier: float = Query(1.0, ge=0.5, le=2.0),
    forecast_days: int = Query(16, ge=1, le=16),
    flood_days: int = Query(30, ge=1, le=30),
    prediction_days: int = Query(365, ge=30, le=365),
    history_years: int = Query(10, ge=3, le=10)
):
    today = date.today()
    hist90_start = (today - timedelta(days=90)).isoformat()
    hist90_end = (today - timedelta(days=1)).isoformat()

    long_hist_start = (today - timedelta(days=365 * history_years)).isoformat()
    long_hist_end = (today - timedelta(days=1)).isoformat()

    async with httpx.AsyncClient() as client:
        tasks = []
        keys = list(LOCATIONS.keys())

        for key in keys:
            meta = LOCATIONS[key]

            forecast_params = {
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "daily": ",".join([
                    "precipitation_sum",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "apparent_temperature_max",
                    "apparent_temperature_min",
                    "et0_fao_evapotranspiration",
                    "wind_speed_10m_max",
                    "wind_gusts_10m_max",
                    "shortwave_radiation_sum"
                ]),
                "forecast_days": forecast_days,
                "timezone": "auto"
            }

            hist90_params = {
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "start_date": hist90_start,
                "end_date": hist90_end,
                "daily": ",".join([
                    "precipitation_sum",
                    "temperature_2m_mean",
                    "et0_fao_evapotranspiration"
                ]),
                "timezone": "auto"
            }

            long_history_params = {
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "start_date": long_hist_start,
                "end_date": long_hist_end,
                "daily": ",".join([
                    "precipitation_sum",
                    "temperature_2m_mean",
                    "et0_fao_evapotranspiration"
                ]),
                "timezone": "auto"
            }

            flood_params = {
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "daily": "river_discharge",
                "forecast_days": flood_days,
                "timezone": "auto"
            }

            tasks.extend([
                fetch_json(client, "https://api.open-meteo.com/v1/forecast", forecast_params),
                fetch_json(client, "https://archive-api.open-meteo.com/v1/archive", hist90_params),
                fetch_json(client, "https://archive-api.open-meteo.com/v1/archive", long_history_params),
                fetch_json(client, "https://flood-api.open-meteo.com/v1/flood", flood_params)
            ])

        responses = await asyncio.gather(*tasks)

    nodes = []

    for i, key in enumerate(keys):
        meta = LOCATIONS[key]

        forecast = responses[i * 4]
        hist90 = responses[i * 4 + 1]
        long_hist = responses[i * 4 + 2]
        flood = responses[i * 4 + 3]

        fd = forecast.get("daily", {}) if isinstance(forecast, dict) else {}
        hd = hist90.get("daily", {}) if isinstance(hist90, dict) else {}
        ld = long_hist.get("daily", {}) if isinstance(long_hist, dict) else {}
        fl = flood.get("daily", {}) if isinstance(flood, dict) else {}

        rainfall_raw = fd.get("precipitation_sum", []) or []
        rainfall = [round(v * precip_modifier, 2) for v in clean_numbers(rainfall_raw)]
        et0 = fd.get("et0_fao_evapotranspiration", []) or []
        tmax = fd.get("temperature_2m_max", []) or []
        tmin = fd.get("temperature_2m_min", []) or []
        apparent_max = fd.get("apparent_temperature_max", []) or []
        apparent_min = fd.get("apparent_temperature_min", []) or []
        wind = fd.get("wind_speed_10m_max", []) or []
        gust = fd.get("wind_gusts_10m_max", []) or []
        radiation = fd.get("shortwave_radiation_sum", []) or []

        hist90_rain = hd.get("precipitation_sum", []) or []
        hist90_temp = hd.get("temperature_2m_mean", []) or []
        hist90_et0 = hd.get("et0_fao_evapotranspiration", []) or []

        discharge = fl.get("river_discharge", []) or []

        prediction = build_climatology_prediction_from_history(ld, prediction_days)

        rain_total = safe_sum(rainfall)
        et0_total = safe_sum(et0)
        water_balance = round(rain_total - et0_total, 2)
        water_balance_day = safe_mean(rainfall) - safe_mean(et0)

        mean_temp = round((safe_mean(tmax) + safe_mean(tmin)) / 2, 2)
        mean_apparent = round((safe_mean(apparent_max) + safe_mean(apparent_min)) / 2, 2)

        soil = estimate_soil_saturation(rainfall, et0)

        peak_discharge = safe_max(discharge)
        flood_risk = flood_risk_class(peak_discharge)
        drought_risk = drought_risk_class(soil, water_balance_day, safe_sum(hist90_rain))

        flood_score = score_from_class(flood_risk)
        drought_score = score_from_class(drought_risk)
        climate_score = climate_risk_score(rain_total, et0_total, safe_max(tmax), safe_max(wind), safe_sum(radiation))
        lulc_score = lulc_pressure_score(
            meta["lulc"],
            meta["irrigation_pressure"],
            meta["urban_pressure"],
            meta["ecosystem_sensitivity"]
        )

        storage_pct = reservoir_storage_percent(meta["dam_capacity_m3"], discharge, precip_modifier)
        reservoir_score = reservoir_stress_score(storage_pct, meta["groundwater_dependency"])

        pop_exposed, pop_exposure_pct = population_exposure(
            meta["population"],
            flood_score,
            drought_score,
            lulc_score,
            climate_score
        )

        population_score = pop_exposure_pct

        composite_score = round(
            climate_score * 0.20 +
            flood_score * 0.20 +
            drought_score * 0.20 +
            population_score * 0.15 +
            lulc_score * 0.15 +
            reservoir_score * 0.10,
            2
        )

        composite_class = class_from_score(composite_score)

        nodes.append({
            "id": key,
            "name": meta["name"],
            "country": meta["country"],
            "iso": meta["iso"],
            "type": meta["type"],
            "coordinates": {"lat": meta["lat"], "lon": meta["lon"]},
            "reference_layers": {
                "population": meta["population"],
                "dam_capacity_m3": meta["dam_capacity_m3"],
                "irrigation_pressure_score": meta["irrigation_pressure"],
                "urban_pressure_score": meta["urban_pressure"],
                "groundwater_dependency_score": meta["groundwater_dependency"],
                "ecosystem_sensitivity_score": meta["ecosystem_sensitivity"]
            },
            "lulc_layer": {
                "profile_percent": meta["lulc"],
                "lulc_pressure_score": lulc_score
            },
            "population_layer": {
                "base_population": meta["population"],
                "population_exposed": pop_exposed,
                "population_exposure_percent": pop_exposure_pct,
                "population_exposure_score": population_score
            },
            "climate_layer": {
                "forecast_rainfall_total_mm": rain_total,
                "forecast_et0_total_mm": et0_total,
                "forecast_water_balance_mm": water_balance,
                "forecast_mean_temperature_c": mean_temp,
                "forecast_max_temperature_c": safe_max(tmax),
                "forecast_min_temperature_c": safe_min(tmin),
                "forecast_mean_apparent_temperature_c": mean_apparent,
                "forecast_max_wind_speed_kmh": safe_max(wind),
                "forecast_max_wind_gust_kmh": safe_max(gust),
                "forecast_solar_radiation_sum_mj_m2": safe_sum(radiation),
                "historical_90d_rainfall_mm": safe_sum(hist90_rain),
                "historical_90d_mean_temperature_c": safe_mean(hist90_temp),
                "historical_90d_et0_mm": safe_sum(hist90_et0),
                "soil_saturation_proxy_m3_m3": soil,
                "climate_risk_score": climate_score
            },
            "drought_layer": {
                "drought_risk": drought_risk,
                "drought_risk_score": drought_score
            },
            "flood_layer": {
                "peak_discharge_m3_s": peak_discharge,
                "mean_discharge_m3_s": safe_mean(discharge),
                "flood_risk": flood_risk,
                "flood_risk_score": flood_score
            },
            "reservoir_layer": {
                "has_reservoir": meta["dam_capacity_m3"] > 0,
                "capacity_m3": meta["dam_capacity_m3"],
                "simulated_storage_percent": storage_pct,
                "reservoir_stress_score": reservoir_score
            },
            "risk_layer": {
                "composite_risk_score": composite_score,
                "composite_risk_class": composite_class
            },
            "prediction_layer": prediction,
            "time_series": {
                "forecast_dates": fd.get("time", []),
                "rainfall_mm": rainfall,
                "et0_mm": et0,
                "temperature_max_c": tmax,
                "temperature_min_c": tmin,
                "apparent_temperature_max_c": apparent_max,
                "apparent_temperature_min_c": apparent_min,
                "wind_speed_max_kmh": wind,
                "wind_gust_max_kmh": gust,
                "solar_radiation_mj_m2": radiation,
                "flood_dates": fl.get("time", []),
                "river_discharge_m3_s": discharge
            },
            "external_links": {
                "copernicus_browser": f"https://browser.dataspace.copernicus.eu/?zoom=11&lat={meta['lat']}&lng={meta['lon']}"
            },
            "raw_errors": {
                "forecast_error": forecast.get("error") if isinstance(forecast, dict) else None,
                "history_90d_error": hist90.get("error") if isinstance(hist90, dict) else None,
                "long_history_error": long_hist.get("error") if isinstance(long_hist, dict) else None,
                "flood_error": flood.get("error") if isinstance(flood, dict) else None
            }
        })

    return {
        "meta": {
            "basin": "Limpopo River Basin",
            "generated_on": today.isoformat(),
            "forecast_days": forecast_days,
            "flood_days": flood_days,
            "prediction_days": prediction_days,
            "history_years": history_years,
            "precip_modifier": precip_modifier,
            "data_note": {
                "online_dynamic_layers": [
                    "rainfall",
                    "ET0",
                    "temperature",
                    "apparent temperature",
                    "wind speed",
                    "wind gust",
                    "solar radiation",
                    "river discharge"
                ],
                "calculated_dynamic_layers": [
                    "water balance",
                    "soil saturation proxy",
                    "climate risk",
                    "drought risk",
                    "flood risk",
                    "population exposure",
                    "reservoir stress",
                    "composite risk",
                    "1-year climatology prediction"
                ],
                "reference_layers": [
                    "LULC profile",
                    "population",
                    "dam capacity",
                    "irrigation pressure",
                    "urban pressure",
                    "groundwater dependency",
                    "ecosystem sensitivity"
                ]
            }
        },
        "basin_indicators": {
            "total_population": sum(n["population_layer"]["base_population"] for n in nodes),
            "total_population_exposed": sum(n["population_layer"]["population_exposed"] for n in nodes),
            "mean_composite_risk_score": safe_mean([n["risk_layer"]["composite_risk_score"] for n in nodes]),
            "mean_climate_risk_score": safe_mean([n["climate_layer"]["climate_risk_score"] for n in nodes]),
            "mean_drought_risk_score": safe_mean([n["drought_layer"]["drought_risk_score"] for n in nodes]),
            "mean_flood_risk_score": safe_mean([n["flood_layer"]["flood_risk_score"] for n in nodes]),
            "mean_lulc_pressure_score": safe_mean([n["lulc_layer"]["lulc_pressure_score"] for n in nodes]),
            "mean_population_exposure_percent": safe_mean([n["population_layer"]["population_exposure_percent"] for n in nodes]),
            "mean_reservoir_stress_score": safe_mean([n["reservoir_layer"]["reservoir_stress_score"] for n in nodes]),
            "mean_soil_saturation_proxy": safe_mean([n["climate_layer"]["soil_saturation_proxy_m3_m3"] for n in nodes]),
            "mean_peak_discharge_m3_s": safe_mean([n["flood_layer"]["peak_discharge_m3_s"] for n in nodes]),
            "mean_prediction_rainfall_mm": safe_mean([n["prediction_layer"]["predicted_total_rainfall_mm"] for n in nodes]),
            "mean_prediction_water_balance_mm": safe_mean([n["prediction_layer"]["predicted_total_water_balance_mm"] for n in nodes])
        },
        "nodes": nodes
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Limpopo Basin Maximum-Factor Digital Twin</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<style>
:root {
    --dark:#0f172a;
    --blue:#2563eb;
    --teal:#0d9488;
    --green:#10b981;
    --amber:#f59e0b;
    --orange:#f97316;
    --red:#e11d48;
    --gray:#64748b;
}
body {
    margin:0;
    font-family:Inter, Arial, sans-serif;
    background:#f1f5f9;
    color:#0f172a;
}
.hero {
    background:linear-gradient(135deg,#020617,#1e3a8a,#0f766e);
    color:white;
    padding:26px 34px;
}
.hero h1 { margin:0; font-size:30px; }
.hero p { margin:6px 0 0 0; color:#cbd5e1; }
.layout { display:flex; min-height:calc(100vh - 90px); }
.sidebar {
    width:370px;
    background:white;
    border-right:1px solid #e2e8f0;
    padding:20px;
    box-sizing:border-box;
}
.main { flex:1; padding:22px; overflow-y:auto; }
.card {
    background:white;
    border-radius:14px;
    padding:18px;
    box-shadow:0 4px 14px rgba(15,23,42,0.06);
    margin-bottom:18px;
}
label {
    display:block;
    font-size:12px;
    font-weight:800;
    text-transform:uppercase;
    color:#475569;
    margin-bottom:6px;
}
select,input,button {
    width:100%;
    padding:10px;
    border-radius:8px;
    border:1px solid #cbd5e1;
    box-sizing:border-box;
    font-size:14px;
}
button {
    background:var(--dark);
    color:white;
    font-weight:800;
    border:none;
    cursor:pointer;
}
.control { margin-bottom:16px; }
.metrics {
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
    gap:16px;
}
.metric { font-size:27px; font-weight:900; margin-top:5px; }
.small { color:#64748b; font-size:12px; line-height:1.5; }
#map { height:560px; border-radius:14px; }
.tabs {
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin-bottom:16px;
}
.tab {
    width:auto;
    background:#e2e8f0;
    color:#0f172a;
}
.tab.active {
    background:#0f172a;
    color:white;
}
.panel { display:none; }
.panel.active { display:block; }
table {
    width:100%;
    border-collapse:collapse;
    font-size:13px;
}
th,td {
    padding:10px;
    border-bottom:1px solid #e2e8f0;
    text-align:left;
}
th {
    background:#f8fafc;
    color:#475569;
    text-transform:uppercase;
    font-size:11px;
}
.badge {
    padding:4px 9px;
    border-radius:999px;
    color:white;
    font-size:11px;
    font-weight:800;
}
.Low { background:var(--green); }
.Moderate { background:var(--amber); }
.High { background:var(--orange); }
.Veryhigh { background:var(--red); }
.status {
    font-size:13px;
    font-weight:800;
    color:var(--blue);
}
.legend {
    background:white;
    padding:10px;
    border-radius:8px;
    font-size:12px;
    box-shadow:0 2px 8px rgba(0,0,0,0.12);
}
.legend span {
    display:inline-block;
    width:13px;
    height:13px;
    border-radius:50%;
    margin-right:6px;
}
pre {
    background:#0f172a;
    color:#e2e8f0;
    border-radius:10px;
    padding:14px;
    max-height:560px;
    overflow:auto;
    font-size:12px;
}
@media(max-width:900px) {
    .layout { flex-direction:column; }
    .sidebar { width:100%; border-right:none; border-bottom:1px solid #e2e8f0; }
}
</style>
</head>

<body>
<div class="hero">
    <h1>Limpopo Basin Maximum-Factor Digital Twin</h1>
    <p>Climate, flood, drought, LULC, population, reservoir, infrastructure and 1-year prediction system</p>
</div>

<div class="layout">
    <div class="sidebar">
        <div class="control">
            <label>Precipitation scenario modifier</label>
            <input type="range" id="precipModifier" min="0.5" max="2.0" step="0.1" value="1.0"
                   oninput="document.getElementById('modifierText').innerText=this.value + 'x'">
            <div class="small">Current: <strong id="modifierText">1.0x</strong></div>
        </div>

        <div class="control">
            <label>Forecast climate days</label>
            <select id="forecastDays">
                <option value="3">3 days</option>
                <option value="7">7 days</option>
                <option value="16" selected>16 days</option>
            </select>
        </div>

        <div class="control">
            <label>Flood forecast days</label>
            <select id="floodDays">
                <option value="7">7 days</option>
                <option value="14">14 days</option>
                <option value="30" selected>30 days</option>
            </select>
        </div>

        <div class="control">
            <label>Prediction horizon</label>
            <select id="predictionDays">
                <option value="30">30 days</option>
                <option value="90">90 days</option>
                <option value="180">180 days</option>
                <option value="365" selected>1 year / 365 days</option>
            </select>
        </div>

        <div class="control">
            <label>History depth for prediction</label>
            <select id="historyYears">
                <option value="3">3 years</option>
                <option value="5">5 years</option>
                <option value="10" selected>10 years</option>
            </select>
        </div>

        <div class="control">
            <label>Map layer</label>
            <select id="mapLayer" onchange="drawMap()">
                <option value="composite">Composite risk</option>
                <option value="climate">Climate risk</option>
                <option value="flood">Flood risk / discharge</option>
                <option value="drought">Drought risk</option>
                <option value="population">Population exposed</option>
                <option value="population_pct">Population exposure percent</option>
                <option value="lulc">LULC pressure</option>
                <option value="urban">Urban land share</option>
                <option value="cropland">Cropland share</option>
                <option value="forest">Forest share</option>
                <option value="water">Water/wetland share</option>
                <option value="bare">Bare land share</option>
                <option value="rain">Forecast rainfall</option>
                <option value="et0">Forecast ET0</option>
                <option value="balance">Forecast water balance</option>
                <option value="temperature">Mean temperature</option>
                <option value="apparent">Apparent temperature</option>
                <option value="wind">Wind speed</option>
                <option value="gust">Wind gust</option>
                <option value="radiation">Solar radiation</option>
                <option value="soil">Soil saturation proxy</option>
                <option value="reservoir">Reservoir storage</option>
                <option value="reservoir_stress">Reservoir stress</option>
                <option value="groundwater">Groundwater dependency</option>
                <option value="irrigation">Irrigation pressure</option>
                <option value="ecosystem">Ecosystem sensitivity</option>
                <option value="prediction_rain">1-year predicted rainfall</option>
                <option value="prediction_balance">1-year predicted water balance</option>
            </select>
        </div>

        <button onclick="loadData()">Update maximum-factor dashboard</button>

        <p id="status" class="status">Initializing...</p>

        <div class="card">
            <strong>Layer types</strong>
            <p class="small">
                Online dynamic: rainfall, ET0, temperature, wind, radiation, discharge.<br>
                Calculated: water balance, flood/drought/climate risk, population exposure, reservoir stress, prediction.<br>
                Reference: LULC, population, dam capacity, irrigation, urban pressure, groundwater dependency.
            </p>
        </div>
    </div>

    <div class="main">
        <div class="metrics">
            <div class="card"><label>Total population exposed</label><div class="metric" id="popMetric">---</div><div class="small">People</div></div>
            <div class="card"><label>Mean composite risk</label><div class="metric" id="riskMetric">---</div><div class="small">0 low, 100 critical</div></div>
            <div class="card"><label>Mean flood discharge</label><div class="metric" id="floodMetric">---</div><div class="small">m³/s</div></div>
            <div class="card"><label>Mean 1-year water balance</label><div class="metric" id="predictionMetric">---</div><div class="small">mm</div></div>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="openTab('mapPanel', this)">Map</button>
            <button class="tab" onclick="openTab('summaryPanel', this)">Summary</button>
            <button class="tab" onclick="openTab('climatePanel', this)">Climate</button>
            <button class="tab" onclick="openTab('floodPanel', this)">Flood</button>
            <button class="tab" onclick="openTab('droughtPanel', this)">Drought</button>
            <button class="tab" onclick="openTab('lulcPanel', this)">LULC</button>
            <button class="tab" onclick="openTab('populationPanel', this)">Population</button>
            <button class="tab" onclick="openTab('reservoirPanel', this)">Reservoir</button>
            <button class="tab" onclick="openTab('riskPanel', this)">Risk</button>
            <button class="tab" onclick="openTab('predictionPanel', this)">Prediction</button>
            <button class="tab" onclick="openTab('apiPanel', this)">API</button>
        </div>

        <div id="mapPanel" class="panel active"><div class="card"><div id="map"></div></div></div>

        <div id="summaryPanel" class="panel">
            <div class="card" style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Node</th><th>Country</th><th>Population</th><th>Exposed</th>
                            <th>Rain</th><th>ET0</th><th>Balance</th><th>Temp</th><th>Discharge</th>
                            <th>Drought</th><th>Flood</th><th>LULC</th><th>Reservoir</th><th>Composite</th>
                        </tr>
                    </thead>
                    <tbody id="summaryRows"></tbody>
                </table>
            </div>
        </div>

        <div id="climatePanel" class="panel">
            <div class="card"><div id="plotClimateBudget"></div></div>
            <div class="card"><div id="plotTemperature"></div></div>
            <div class="card"><div id="plotWindRadiation"></div></div>
        </div>

        <div id="floodPanel" class="panel">
            <div class="card"><div id="plotFloodBars"></div></div>
            <div class="card"><div id="plotFloodPopulation"></div></div>
        </div>

        <div id="droughtPanel" class="panel">
            <div class="card"><div id="plotDrought"></div></div>
            <div class="card"><div id="plotSoilBalance"></div></div>
        </div>

        <div id="lulcPanel" class="panel">
            <div class="card"><div id="plotLulcStacked"></div></div>
            <div class="card"><div id="plotLulcRisk"></div></div>
        </div>

        <div id="populationPanel" class="panel">
            <div class="card"><div id="plotPopulation"></div></div>
            <div class="card"><div id="plotExposurePercent"></div></div>
        </div>

        <div id="reservoirPanel" class="panel">
            <div class="card"><div id="plotReservoir"></div></div>
            <div class="card"><div id="plotInfrastructure"></div></div>
        </div>

        <div id="riskPanel" class="panel">
            <div class="card"><div id="plotCompositeRisk"></div></div>
            <div class="card"><div id="plotRiskComponents"></div></div>
            <div class="card"><div id="plotRiskScatter"></div></div>
        </div>

        <div id="predictionPanel" class="panel">
            <div class="card">
                <label>Select node for time-series</label>
                <select id="nodeSelect" onchange="drawTimeSeries()"></select>
            </div>
            <div class="card"><div id="plotPredictionClimate"></div></div>
            <div class="card"><div id="plotPredictionBalance"></div></div>
            <div class="card"><div id="plotForecastClimate"></div></div>
            <div class="card"><div id="plotFloodTime"></div></div>
        </div>

        <div id="apiPanel" class="panel">
            <div class="card">
                <p><a href="/api/v8/max-factors" target="_blank">Open /api/v8/max-factors</a></p>
                <p><a href="/docs" target="_blank">Open /docs</a></p>
                <pre id="apiBox">Loading...</pre>
            </div>
        </div>
    </div>
</div>

<script>
let latestData = null;
let map;
let markerLayer;

function openTab(id, btn) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    btn.classList.add('active');
    if (id === 'mapPanel' && map) setTimeout(() => map.invalidateSize(), 200);
}

function fmt(v, d=2) {
    if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
    if (typeof v === 'number') return v.toFixed(d);
    return v;
}

function badge(v) {
    const cls = v === 'Very high' ? 'Veryhigh' : v;
    return `<span class="badge ${cls}">${v}</span>`;
}

function initMap() {
    map = L.map('map').setView([-23.8, 30.2], 6);

    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution:'OpenStreetMap'}).addTo(map);
    const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {attribution:'OpenTopoMap'});

    L.control.layers({'OpenStreetMap':osm, 'Topographic':topo}).addTo(map);

    markerLayer = L.layerGroup().addTo(map);

    L.polyline([
        [-25.20,26.90],[-24.65,25.91],[-21.17,27.51],[-22.22,30.00],
        [-24.00,31.50],[-23.88,32.16],[-24.53,32.98],[-25.05,33.65]
    ], {color:'#2563eb', weight:4, dashArray:'5,8', opacity:0.75})
    .addTo(map).bindPopup('Approximate Limpopo monitoring corridor');

    const legend = L.control({position:'bottomright'});
    legend.onAdd = function() {
        const div = L.DomUtil.create('div','legend');
        div.innerHTML = `
            <strong>Map intensity</strong><br>
            <span style="background:#10b981"></span> Low<br>
            <span style="background:#f59e0b"></span> Moderate<br>
            <span style="background:#f97316"></span> High<br>
            <span style="background:#e11d48"></span> Very high
        `;
        return div;
    };
    legend.addTo(map);
}

function classValue(label) {
    if (label === 'Very high') return 95;
    if (label === 'High') return 75;
    if (label === 'Moderate') return 50;
    return 20;
}

function valueForMap(n, layer) {
    const c = n.climate_layer;
    const f = n.flood_layer;
    const d = n.drought_layer;
    const l = n.lulc_layer;
    const p = n.population_layer;
    const r = n.reservoir_layer;
    const ref = n.reference_layers;
    const pred = n.prediction_layer;

    if (layer === 'composite') return n.risk_layer.composite_risk_score;
    if (layer === 'climate') return c.climate_risk_score;
    if (layer === 'flood') return f.peak_discharge_m3_s;
    if (layer === 'drought') return d.drought_risk_score;
    if (layer === 'population') return p.population_exposed;
    if (layer === 'population_pct') return p.population_exposure_percent;
    if (layer === 'lulc') return l.lulc_pressure_score;
    if (layer === 'urban') return l.profile_percent.urban;
    if (layer === 'cropland') return l.profile_percent.cropland;
    if (layer === 'forest') return l.profile_percent.forest;
    if (layer === 'water') return l.profile_percent.water;
    if (layer === 'bare') return l.profile_percent.bare;
    if (layer === 'rain') return c.forecast_rainfall_total_mm;
    if (layer === 'et0') return c.forecast_et0_total_mm;
    if (layer === 'balance') return c.forecast_water_balance_mm;
    if (layer === 'temperature') return c.forecast_mean_temperature_c;
    if (layer === 'apparent') return c.forecast_mean_apparent_temperature_c;
    if (layer === 'wind') return c.forecast_max_wind_speed_kmh;
    if (layer === 'gust') return c.forecast_max_wind_gust_kmh;
    if (layer === 'radiation') return c.forecast_solar_radiation_sum_mj_m2;
    if (layer === 'soil') return c.soil_saturation_proxy_m3_m3;
    if (layer === 'reservoir') return r.simulated_storage_percent || 0;
    if (layer === 'reservoir_stress') return r.reservoir_stress_score;
    if (layer === 'groundwater') return ref.groundwater_dependency_score;
    if (layer === 'irrigation') return ref.irrigation_pressure_score;
    if (layer === 'ecosystem') return ref.ecosystem_sensitivity_score;
    if (layer === 'prediction_rain') return pred.predicted_total_rainfall_mm;
    if (layer === 'prediction_balance') return pred.predicted_total_water_balance_mm;
    return 0;
}

function colorForValue(v, maxv, layer) {
    if (layer === 'reservoir' || layer === 'soil' || layer === 'forest' || layer === 'water') {
        const ratio = maxv <= 0 ? 0 : v / maxv;
        if (ratio < 0.35) return '#e11d48';
        if (ratio < 0.60) return '#f59e0b';
        return '#10b981';
    }

    if (layer === 'balance' || layer === 'prediction_balance') {
        if (v < -300) return '#e11d48';
        if (v < -100) return '#f97316';
        if (v < 0) return '#f59e0b';
        return '#10b981';
    }

    const ratio = maxv <= 0 ? 0 : v / maxv;
    if (ratio >= 0.75) return '#e11d48';
    if (ratio >= 0.50) return '#f97316';
    if (ratio >= 0.25) return '#f59e0b';
    return '#10b981';
}

function drawMap() {
    if (!latestData || !map) return;

    markerLayer.clearLayers();

    const layer = document.getElementById('mapLayer').value;
    const values = latestData.nodes.map(n => Math.abs(valueForMap(n, layer)));
    const maxv = Math.max(...values, 1);
    const bounds = [];

    latestData.nodes.forEach(n => {
        const v = valueForMap(n, layer);
        const color = colorForValue(v, maxv, layer);
        const radius = 9 + 28 * (Math.abs(v) / maxv);

        const marker = L.circleMarker([n.coordinates.lat, n.coordinates.lon], {
            radius:radius,
            color:color,
            fillColor:color,
            fillOpacity:0.65,
            weight:2
        }).addTo(markerLayer);

        marker.bindPopup(`
            <strong>${n.name}</strong><br>
            <small>${n.country} | ${n.type}</small><hr>
            <b>Selected layer value:</b> ${fmt(v)}<br>
            <b>Composite risk:</b> ${fmt(n.risk_layer.composite_risk_score)} (${n.risk_layer.composite_risk_class})<br>
            <b>Climate risk:</b> ${fmt(n.climate_layer.climate_risk_score)}<br>
            <b>Drought:</b> ${n.drought_layer.drought_risk}<br>
            <b>Flood:</b> ${n.flood_layer.flood_risk}, ${fmt(n.flood_layer.peak_discharge_m3_s)} m³/s<br>
            <b>Population exposed:</b> ${n.population_layer.population_exposed.toLocaleString()} (${fmt(n.population_layer.population_exposure_percent)}%)<br>
            <b>LULC pressure:</b> ${fmt(n.lulc_layer.lulc_pressure_score)}<br>
            <b>Rain:</b> ${fmt(n.climate_layer.forecast_rainfall_total_mm)} mm | <b>ET0:</b> ${fmt(n.climate_layer.forecast_et0_total_mm)} mm<br>
            <b>1-year predicted rain:</b> ${fmt(n.prediction_layer.predicted_total_rainfall_mm)} mm<br>
            <a href="${n.external_links.copernicus_browser}" target="_blank">Open Copernicus Browser</a>
        `);

        bounds.push([n.coordinates.lat, n.coordinates.lon]);
    });

    if (bounds.length > 0) map.fitBounds(bounds, {padding:[35,35]});
}

async function loadData() {
    const status = document.getElementById('status');
    status.innerText = 'Loading maximum-factor online data. First run can take 60–120 seconds on Render Free...';

    const precip = document.getElementById('precipModifier').value;
    const forecastDays = document.getElementById('forecastDays').value;
    const floodDays = document.getElementById('floodDays').value;
    const predictionDays = document.getElementById('predictionDays').value;
    const historyYears = document.getElementById('historyYears').value;

    const url = `/api/v8/max-factors?precip_modifier=${precip}&forecast_days=${forecastDays}&flood_days=${floodDays}&prediction_days=${predictionDays}&history_years=${historyYears}`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        latestData = data;

        document.getElementById('apiBox').textContent = JSON.stringify(data, null, 2);

        document.getElementById('popMetric').innerText = data.basin_indicators.total_population_exposed.toLocaleString();
        document.getElementById('riskMetric').innerText = fmt(data.basin_indicators.mean_composite_risk_score) + ' / 100';
        document.getElementById('floodMetric').innerText = fmt(data.basin_indicators.mean_peak_discharge_m3_s) + ' m³/s';
        document.getElementById('predictionMetric').innerText = fmt(data.basin_indicators.mean_prediction_water_balance_mm) + ' mm';

        fillTable();
        fillNodeSelector();
        drawMap();
        drawAllPlots();
        drawTimeSeries();

        status.innerText = 'Maximum-factor dashboard updated successfully.';
    } catch (err) {
        status.innerText = 'Error loading dashboard: ' + err;
    }
}

function fillTable() {
    let html = '';

    latestData.nodes.forEach(n => {
        html += `
            <tr>
                <td><strong>${n.name}</strong></td>
                <td>${n.country}</td>
                <td>${n.population_layer.base_population.toLocaleString()}</td>
                <td>${n.population_layer.population_exposed.toLocaleString()}</td>
                <td>${fmt(n.climate_layer.forecast_rainfall_total_mm)}</td>
                <td>${fmt(n.climate_layer.forecast_et0_total_mm)}</td>
                <td>${fmt(n.climate_layer.forecast_water_balance_mm)}</td>
                <td>${fmt(n.climate_layer.forecast_mean_temperature_c)}</td>
                <td>${fmt(n.flood_layer.peak_discharge_m3_s)}</td>
                <td>${badge(n.drought_layer.drought_risk)}</td>
                <td>${badge(n.flood_layer.flood_risk)}</td>
                <td>${fmt(n.lulc_layer.lulc_pressure_score)}</td>
                <td>${fmt(n.reservoir_layer.reservoir_stress_score)}</td>
                <td><strong>${fmt(n.risk_layer.composite_risk_score)}</strong></td>
            </tr>
        `;
    });

    document.getElementById('summaryRows').innerHTML = html;
}

function fillNodeSelector() {
    const select = document.getElementById('nodeSelect');
    select.innerHTML = '';

    latestData.nodes.forEach((n, i) => {
        const option = document.createElement('option');
        option.value = i;
        option.textContent = n.name;
        select.appendChild(option);
    });
}

function layout(title, b=110) {
    return {
        title:title,
        paper_bgcolor:'white',
        plot_bgcolor:'white',
        font:{family:'Inter, Arial, sans-serif', color:'#0f172a'},
        margin:{l:60,r:35,t:60,b:b},
        xaxis:{gridcolor:'#f1f5f9'},
        yaxis:{gridcolor:'#f1f5f9'}
    };
}

function drawAllPlots() {
    const nodes = latestData.nodes;
    const names = nodes.map(n => n.name);

    Plotly.newPlot('plotClimateBudget', [
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_rainfall_total_mm), type:'bar', name:'Rainfall'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_et0_total_mm), type:'bar', name:'ET0'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_water_balance_mm), type:'bar', name:'Water balance'}
    ], {...layout('Climate water budget: rainfall, ET0 and water balance'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotTemperature', [
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_mean_temperature_c), type:'bar', name:'Mean temperature'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_max_temperature_c), type:'bar', name:'Max temperature'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_mean_apparent_temperature_c), type:'bar', name:'Apparent temperature'}
    ], {...layout('Temperature and apparent temperature by node'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotWindRadiation', [
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_max_wind_speed_kmh), type:'bar', name:'Wind speed'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_max_wind_gust_kmh), type:'bar', name:'Wind gust'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_solar_radiation_sum_mj_m2), type:'bar', name:'Solar radiation'}
    ], {...layout('Wind, gust and solar radiation'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotFloodBars', [
        {x:names, y:nodes.map(n=>n.flood_layer.peak_discharge_m3_s), type:'bar', name:'Peak discharge'},
        {x:names, y:nodes.map(n=>n.flood_layer.mean_discharge_m3_s), type:'bar', name:'Mean discharge'},
        {x:names, y:nodes.map(n=>n.flood_layer.flood_risk_score), type:'bar', name:'Flood risk score'}
    ], {...layout('Flood discharge and flood risk'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotFloodPopulation', [{
        x:nodes.map(n=>n.flood_layer.peak_discharge_m3_s),
        y:nodes.map(n=>n.population_layer.population_exposed),
        text:names,
        type:'scatter',
        mode:'markers+text',
        textposition:'top center',
        marker:{size:nodes.map(n=>12+n.risk_layer.composite_risk_score/3), color:nodes.map(n=>n.flood_layer.flood_risk_score), colorscale:'YlOrRd', showscale:true}
    }], {...layout('Flood discharge vs population exposed', 80), xaxis:{title:'Peak discharge, m³/s'}, yaxis:{title:'Population exposed'}}, {responsive:true});

    Plotly.newPlot('plotDrought', [
        {x:names, y:nodes.map(n=>n.drought_layer.drought_risk_score), type:'bar', name:'Drought risk score'},
        {x:names, y:nodes.map(n=>n.climate_layer.historical_90d_rainfall_mm), type:'bar', name:'90d rainfall'}
    ], {...layout('Drought risk and 90-day antecedent rainfall'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotSoilBalance', [
        {x:names, y:nodes.map(n=>n.climate_layer.soil_saturation_proxy_m3_m3), type:'bar', name:'Soil saturation proxy'},
        {x:names, y:nodes.map(n=>n.climate_layer.forecast_water_balance_mm), type:'bar', name:'Water balance'}
    ], {...layout('Soil saturation proxy and forecast water balance'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotLulcStacked', [
        {x:names, y:nodes.map(n=>n.lulc_layer.profile_percent.urban), type:'bar', name:'Urban'},
        {x:names, y:nodes.map(n=>n.lulc_layer.profile_percent.cropland), type:'bar', name:'Cropland'},
        {x:names, y:nodes.map(n=>n.lulc_layer.profile_percent.grassland), type:'bar', name:'Grassland'},
        {x:names, y:nodes.map(n=>n.lulc_layer.profile_percent.forest), type:'bar', name:'Forest'},
        {x:names, y:nodes.map(n=>n.lulc_layer.profile_percent.water), type:'bar', name:'Water'},
        {x:names, y:nodes.map(n=>n.lulc_layer.profile_percent.bare), type:'bar', name:'Bare'}
    ], {...layout('LULC composition by monitoring node'), barmode:'stack', yaxis:{title:'Percent'}}, {responsive:true});

    Plotly.newPlot('plotLulcRisk', [
        {x:names, y:nodes.map(n=>n.lulc_layer.lulc_pressure_score), type:'bar', name:'LULC pressure'},
        {x:names, y:nodes.map(n=>n.reference_layers.irrigation_pressure_score), type:'bar', name:'Irrigation pressure'},
        {x:names, y:nodes.map(n=>n.reference_layers.urban_pressure_score), type:'bar', name:'Urban pressure'}
    ], {...layout('LULC, irrigation and urban pressure'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotPopulation', [
        {x:names, y:nodes.map(n=>n.population_layer.base_population), type:'bar', name:'Base population'},
        {x:names, y:nodes.map(n=>n.population_layer.population_exposed), type:'bar', name:'Population exposed'}
    ], {...layout('Population and exposed population'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotExposurePercent', [
        {x:names, y:nodes.map(n=>n.population_layer.population_exposure_percent), type:'bar', name:'Exposure percent'}
    ], {...layout('Population exposure percentage'), yaxis:{title:'Percent'}}, {responsive:true});

    Plotly.newPlot('plotReservoir', [
        {x:names, y:nodes.map(n=>n.reservoir_layer.simulated_storage_percent || 0), type:'bar', name:'Storage %'},
        {x:names, y:nodes.map(n=>n.reservoir_layer.reservoir_stress_score), type:'bar', name:'Reservoir stress'}
    ], {...layout('Reservoir storage and reservoir stress'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotInfrastructure', [
        {x:names, y:nodes.map(n=>n.reference_layers.groundwater_dependency_score), type:'bar', name:'Groundwater dependency'},
        {x:names, y:nodes.map(n=>n.reference_layers.ecosystem_sensitivity_score), type:'bar', name:'Ecosystem sensitivity'},
        {x:names, y:nodes.map(n=>n.reference_layers.irrigation_pressure_score), type:'bar', name:'Irrigation pressure'}
    ], {...layout('Infrastructure and environmental sensitivity'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotCompositeRisk', [
        {x:names, y:nodes.map(n=>n.risk_layer.composite_risk_score), type:'bar', name:'Composite risk'}
    ], {...layout('Composite multi-factor risk score'), yaxis:{range:[0,100], title:'Score'}}, {responsive:true});

    Plotly.newPlot('plotRiskComponents', [
        {x:names, y:nodes.map(n=>n.climate_layer.climate_risk_score), type:'bar', name:'Climate'},
        {x:names, y:nodes.map(n=>n.flood_layer.flood_risk_score), type:'bar', name:'Flood'},
        {x:names, y:nodes.map(n=>n.drought_layer.drought_risk_score), type:'bar', name:'Drought'},
        {x:names, y:nodes.map(n=>n.lulc_layer.lulc_pressure_score), type:'bar', name:'LULC'},
        {x:names, y:nodes.map(n=>n.population_layer.population_exposure_score), type:'bar', name:'Population'},
        {x:names, y:nodes.map(n=>n.reservoir_layer.reservoir_stress_score), type:'bar', name:'Reservoir'}
    ], {...layout('Risk component breakdown'), barmode:'group'}, {responsive:true});

    Plotly.newPlot('plotRiskScatter', [{
        x:nodes.map(n=>n.lulc_layer.lulc_pressure_score),
        y:nodes.map(n=>n.risk_layer.composite_risk_score),
        text:names,
        type:'scatter',
        mode:'markers+text',
        textposition:'top center',
        marker:{size:nodes.map(n=>12+n.population_layer.population_exposure_percent/2), color:nodes.map(n=>n.climate_layer.climate_risk_score), colorscale:'Portland', showscale:true}
    }], {...layout('LULC pressure vs composite risk', 80), xaxis:{title:'LULC pressure'}, yaxis:{title:'Composite risk'}}, {responsive:true});
}

function drawTimeSeries() {
    if (!latestData) return;

    const idx = Number(document.getElementById('nodeSelect').value || 0);
    const n = latestData.nodes[idx];
    const ts = n.time_series;
    const pred = n.prediction_layer;

    Plotly.newPlot('plotPredictionClimate', [
        {x:pred.dates, y:pred.predicted_rainfall_mm, type:'scatter', mode:'lines', name:'Predicted rainfall'},
        {x:pred.dates, y:pred.predicted_et0_mm, type:'scatter', mode:'lines', name:'Predicted ET0'},
        {x:pred.dates, y:pred.predicted_temperature_c, type:'scatter', mode:'lines', name:'Predicted temperature'}
    ], {...layout('Prediction time-series: rainfall, ET0 and temperature - ' + n.name, 70), yaxis:{title:'Mixed units'}}, {responsive:true});

    Plotly.newPlot('plotPredictionBalance', [
        {x:pred.dates, y:pred.predicted_water_balance_mm, type:'scatter', mode:'lines', fill:'tozeroy', name:'Predicted water balance'}
    ], {...layout('Predicted water-balance time-series - ' + n.name, 70), yaxis:{title:'Rainfall - ET0, mm/day'}}, {responsive:true});

    Plotly.newPlot('plotForecastClimate', [
        {x:ts.forecast_dates, y:ts.rainfall_mm, type:'scatter', mode:'lines+markers', name:'Forecast rainfall'},
        {x:ts.forecast_dates, y:ts.et0_mm, type:'scatter', mode:'lines+markers', name:'Forecast ET0'},
        {x:ts.forecast_dates, y:ts.temperature_max_c, type:'scatter', mode:'lines+markers', name:'Max temp'},
        {x:ts.forecast_dates, y:ts.wind_speed_max_kmh, type:'scatter', mode:'lines+markers', name:'Wind speed'},
        {x:ts.forecast_dates, y:ts.solar_radiation_mj_m2, type:'scatter', mode:'lines+markers', name:'Solar radiation'}
    ], {...layout('Short-term climate time-series - ' + n.name, 70), yaxis:{title:'Mixed climate units'}}, {responsive:true});

    Plotly.newPlot('plotFloodTime', [
        {x:ts.flood_dates, y:ts.river_discharge_m3_s, type:'scatter', mode:'lines+markers', fill:'tozeroy', name:'River discharge'}
    ], {...layout('Flood discharge time-series - ' + n.name, 70), yaxis:{title:'m³/s'}}, {responsive:true});
}

document.addEventListener('DOMContentLoaded', function() {
    initMap();
    loadData();
});
</script>
</body>
</html>
    """


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
