"""weather.py — current conditions + 3-day forecast via open-meteo.com.

Free JSON HTTPS API, no key required. Uses amiga.https for the fetch
and stdlib json to parse. Default: London. Pass lat,lon or a city
name (limited built-in table) on the command line:

    python3 python3:examples/weather.py
    python3 python3:examples/weather.py 40.71,-74.01
    python3 python3:examples/weather.py tokyo
"""
import sys, json
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


CITIES = {
    "london":    (51.51,  -0.13),
    "newyork":   (40.71, -74.01),
    "tokyo":     (35.68, 139.65),
    "sydney":    (-33.87, 151.21),
    "paris":     (48.85,   2.35),
    "berlin":    (52.52,  13.41),
    "sanfrancisco": (37.77, -122.42),
    "toronto":   (43.65, -79.38),
    "cape town": (-33.92, 18.42),
    "reykjavik": (64.15, -21.94),
}

# https://open-meteo.com/en/docs — weather codes
WCODE = {
    0:  "clear",           1:  "mainly clear",  2:  "partly cloudy",
    3:  "overcast",        45: "fog",           48: "rime fog",
    51: "drizzle (light)", 53: "drizzle",       55: "drizzle (heavy)",
    61: "rain (light)",    63: "rain",          65: "rain (heavy)",
    71: "snow (light)",    73: "snow",          75: "snow (heavy)",
    77: "snow grains",     80: "rain showers",  81: "rain showers (heavy)",
    82: "violent rain",    85: "snow showers",  86: "snow showers (heavy)",
    95: "thunderstorm",    96: "thunder+hail",  99: "thunder+hail (heavy)",
}


def parse_arg(arg):
    """Return (lat, lon, label)."""
    if not arg:
        return CITIES["london"] + ("London",)
    key = arg.strip().lower().replace(" ", "")
    if key in CITIES:
        lat, lon = CITIES[key]
        return lat, lon, arg
    if "," in arg:
        lat, lon = [float(x) for x in arg.split(",", 1)]
        return lat, lon, f"{lat:.2f},{lon:.2f}"
    raise SystemExit(f"unknown location: {arg} — try a coord pair or one of "
                     f"{', '.join(CITIES)}")


def fetch(lat, lon):
    from amiga import https as ah
    url = (f"https://api.open-meteo.com/v1/forecast?"
           f"latitude={lat:.4f}&longitude={lon:.4f}"
           f"&current=temperature_2m,wind_speed_10m,weather_code"
           f"&daily=temperature_2m_max,temperature_2m_min,weather_code"
           f"&timezone=auto&forecast_days=3")
    status, hdrs, body = ah.get(url, timeout=30)
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {body[:200]!r}")
    return json.loads(body)


def show(loc, data):
    print(f"=== weather @ {loc} ===\n")
    cur = data.get("current", {})
    tunit  = data.get("current_units", {}).get("temperature_2m", "°C")
    wunit  = data.get("current_units", {}).get("wind_speed_10m", "km/h")
    code   = cur.get("weather_code")
    print(f"Now: {cur.get('temperature_2m'):.1f}{tunit}"
          f"    {WCODE.get(code, f'code {code}')}"
          f"    wind {cur.get('wind_speed_10m'):.1f} {wunit}")
    print()
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    hi    = daily.get("temperature_2m_max", [])
    lo    = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])
    print(f"{'Date':<12} {'Hi':>6} {'Lo':>6}  Conditions")
    for d, h, l, c in zip(dates, hi, lo, codes):
        print(f"{d:<12} {h:>6.1f} {l:>6.1f}  {WCODE.get(c, 'code '+str(c))}")


def main():
    arg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    lat, lon, label = parse_arg(arg)
    print(f"weather: fetching {label} ({lat:.2f}, {lon:.2f})...", flush=True)
    data = fetch(lat, lon)
    show(label, data)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
