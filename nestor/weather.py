# Weather and sun times for the briefing, from Open-Meteo (free, no key). The home location ("Princeton, NJ", a ZIP
# code, or "40.35,-74.66") is looked up once and remembered in data/location.json.
import json
import os
import re
import urllib.parse
import urllib.request
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
LOCATION_PATH = os.path.join(DATA_DIR, "location.json")
RAIN_LIKELY_PERCENT = 50
COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
US_STATES = {code: name.replace("_", " ") for code, name in (pair.split("=") for pair in (
    "AL=Alabama AK=Alaska AZ=Arizona AR=Arkansas CA=California CO=Colorado CT=Connecticut DE=Delaware "
    "DC=District_of_Columbia FL=Florida GA=Georgia HI=Hawaii ID=Idaho IL=Illinois IN=Indiana IA=Iowa KS=Kansas "
    "KY=Kentucky LA=Louisiana ME=Maine MD=Maryland MA=Massachusetts MI=Michigan MN=Minnesota MS=Mississippi "
    "MO=Missouri MT=Montana NE=Nebraska NV=Nevada NH=New_Hampshire NJ=New_Jersey NM=New_Mexico NY=New_York "
    "NC=North_Carolina ND=North_Dakota OH=Ohio OK=Oklahoma OR=Oregon PA=Pennsylvania RI=Rhode_Island "
    "SC=South_Carolina SD=South_Dakota TN=Tennessee TX=Texas UT=Utah VT=Vermont VA=Virginia WA=Washington "
    "WV=West_Virginia WI=Wisconsin WY=Wyoming").split())}
WEATHER_WORDS = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
                 51: "drizzly", 53: "drizzly", 55: "drizzly", 56: "freezing drizzle", 57: "freezing drizzle",
                 61: "light rain", 63: "rainy", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
                 71: "light snow", 73: "snowy", 75: "heavy snow", 77: "snowy", 80: "showers", 81: "showers",
                 82: "heavy showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorms",
                 96: "thunderstorms with hail", 99: "thunderstorms with hail"}

# Fetch a URL with query parameters and decode the JSON answer
def fetch_json(url, params):
    weather_request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                             headers={"User-Agent": "nestor"})
    with urllib.request.urlopen(weather_request, timeout=15) as response:
        return json.load(response)

# Read the remembered location, if it was found for this same setting
def read_saved_location(setting):
    saved = read_json(LOCATION_PATH, {})
    return saved if saved.get("setting") == setting else None

# Pick the geocoding result in the region named after the comma ("NJ", "New Jersey", "UK"), else the first one
def best_result(results, region):
    region = region.strip().lower()
    wanted = {region, US_STATES.get(region.upper(), "").lower()} - {""}

    # Look for a result whose state, country or country code matches
    for result in results:
        names = {str(result.get(key, "")).lower() for key in ("admin1", "country", "country_code")}

        # The first match wins
        if wanted & names:
            return result
    return None if region else results[0]

# Find the latitude and longitude for the home_location setting; raises ValueError if it can't be found
def find_location(setting):
    match = COORDINATES.match(setting)

    # Coordinates given directly need no lookup
    if match:
        return {"setting": setting, "name": setting, "latitude": float(match.group(1)),
                "longitude": float(match.group(2))}
    saved = read_saved_location(setting)

    # Reuse the earlier lookup
    if saved:
        return saved
    place_name, _, region = setting.partition(",")
    results = fetch_json(GEOCODE_URL, {"name": place_name.strip(), "count": 20, "language": "en",
                                       "format": "json"}).get("results") or []
    result = best_result(results, region) if results else None

    # Nothing matched: say what to change
    if not result:
        raise ValueError(f"home_location {setting!r} wasn't found; try 'Town, ST', a ZIP code, or 'lat,lon'")
    location = {"setting": setting, "name": f"{result['name']}, {result.get('admin1', result.get('country', ''))}",
                "latitude": result["latitude"], "longitude": result["longitude"]}
    write_json(LOCATION_PATH, location)
    return location

# The weather today (or days_ahead days from now) as JSON-ready data: now (today only), high, low, conditions, when
# rain is likely, sunrise and sunset
def forecast(setting, temperature_unit="fahrenheit", days_ahead=0):
    location = find_location(setting)
    answer = fetch_json(FORECAST_URL, {
        "latitude": location["latitude"], "longitude": location["longitude"], "timezone": "auto",
        "current": "temperature_2m,weather_code", "hourly": "precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max,weather_code",
        "temperature_unit": temperature_unit, "forecast_days": days_ahead + 1})
    daily = answer["daily"]
    day_text = daily["time"][days_ahead]
    from_hour = answer["current"]["time"][:13] if days_ahead == 0 else day_text + "T00"  # Today: from now on
    rain_from = None

    # The first hour of the day (from now on, for today) with a good chance of rain
    for hour_text, chance in zip(answer["hourly"]["time"], answer["hourly"]["precipitation_probability"]):
        # Only hours on the day, later than from_hour, with a high enough chance
        if hour_text[:10] == day_text and hour_text[:13] >= from_hour and chance is not None and \
                chance >= RAIN_LIKELY_PERCENT:
            rain_from = hour_text[11:16]
            break

    # Today has the temperature right now; a later day only its own forecast
    if days_ahead == 0:
        now = round(answer["current"]["temperature_2m"])
        conditions = WEATHER_WORDS.get(answer["current"]["weather_code"], "mixed")
    else:
        now = None
        conditions = WEATHER_WORDS.get(daily["weather_code"][days_ahead], "mixed")
    return {"place": location["name"], "unit": "F" if temperature_unit == "fahrenheit" else "C", "date": day_text,
            "now": now, "conditions": conditions, "high": round(daily["temperature_2m_max"][days_ahead]),
            "low": round(daily["temperature_2m_min"][days_ahead]),
            "rain_chance": daily["precipitation_probability_max"][days_ahead], "rain_from": rain_from,
            "sunrise": daily["sunrise"][days_ahead][11:16], "sunset": daily["sunset"][days_ahead][11:16]}
