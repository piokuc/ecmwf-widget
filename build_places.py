#!/usr/bin/env python3
"""Build the catalogue of world places used by the widget.

Combines a country list (capital names, country codes, flags) with a city
list (exact coordinates and elevation) and writes ``world_places.yml``.

    python build_places.py                 # write world_places.yml
    python build_places.py --check         # report how well capitals matched
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata

COUNTRIES_URL = "https://unpkg.com/world-countries@5.0.0/countries.json"
CITIES_URL = "https://raw.githubusercontent.com/lutangar/cities.json/master/cities.json"
OUTPUT = "world_places.yml"

#: Major cities and notable places worth following, on top of the capitals.
EXTRA = {
    "PL": ["Gliwice", "Górki Wielkie", "Kraków", "Wrocław", "Poznań", "Gdańsk", "Zakopane"],
    "US": ["New York", "Los Angeles", "Chicago", "Houston", "Seattle", "Miami", "Denver"],
    "GB": ["Manchester", "Edinburgh", "Birmingham", "Glasgow"],
    "DE": ["Munich", "Hamburg", "Frankfurt", "Cologne", "Dresden"],
    "FR": ["Marseille", "Lyon", "Nice", "Strasbourg"],
    "IT": ["Milan", "Naples", "Venice", "Florence", "Turin"],
    "ES": ["Barcelona", "Valencia", "Seville", "Bilbao"],
    "JP": ["Osaka", "Kyoto", "Sapporo", "Fukuoka"],
    "CN": ["Shanghai", "Guangzhou", "Shenzhen", "Chengdu"],
    "IN": ["Mumbai", "Delhi", "Bangalore", "Kolkata", "Chennai"],
    "BR": ["Rio de Janeiro", "Brasilia", "Salvador", "Foz do Iguacu"],
    "AR": ["Cordoba", "Mendoza", "Bariloche"],
    "CH": ["Geneva", "Zurich", "Bern", "Zermatt", "Interlaken"],
    "AT": ["Salzburg", "Innsbruck", "Vienna"],
    "CZ": ["Prague", "Brno", "Ostrava"],
    "NO": ["Bergen", "Tromso", "Oslo"],
    "SE": ["Stockholm", "Gothenburg"],
    "FI": ["Rovaniemi", "Helsinki"],
    "IS": ["Reykjavik"],
    "GR": ["Athens", "Heraklion", "Thessaloniki"],
    "TR": ["Istanbul", "Ankara", "Antalya"],
    "MA": ["Marrakesh", "Fes", "Chefchaouen"],
    "EG": ["Alexandria", "Luxor", "Sharm el Sheikh"],
    "ZA": ["Cape Town", "Durban", "Johannesburg"],
    "AU": ["Melbourne", "Brisbane", "Perth", "Sydney", "Darwin"],
    "NZ": ["Queenstown", "Wellington", "Auckland"],
    "CA": ["Toronto", "Montreal", "Vancouver", "Calgary"],
    "MX": ["Cancun", "Guadalajara", "Monterrey"],
    "RU": ["Saint Petersburg", "Sochi", "Vladivostok"],
    "AE": ["Dubai", "Abu Dhabi"],
    "IL": ["Tel Aviv", "Jerusalem", "Eilat"],
    "PT": ["Porto", "Faro", "Lisbon"],
    "IE": ["Dublin", "Galway"],
    "RO": ["Brasov", "Cluj-Napoca", "Bucharest"],
    "HU": ["Budapest", "Eger", "Keszthely"],
    "SK": ["Bratislava", "Poprad"],
    "HR": ["Dubrovnik", "Zagreb"],
    "SI": ["Ljubljana", "Bled"],
    "LT": ["Vilnius", "Nida"],
    "LV": ["Riga", "Sigulda"],
    "EE": ["Tallinn", "Tartu"],
    "IS2": [],
    "MX2": [],
    "CL": ["Santiago", "Valparaiso", "Punta Arenas"],
    "PE": ["Cusco", "Lima"],
    "CO": ["Bogota", "Medellin", "Cartagena"],
    "NZ2": [],
    "FJ": ["Suva"],
    "FJ2": [],
    "LA": ["Luang Prabang"],
    "KH": ["Siem Reap"],
    "NP": ["Pokhara"],
    "TZ": ["Arusha", "Zanzibar City"],
    "KE": ["Mombasa"],
    "MA2": [],
    "GL": ["Nuuk"],
    "IS3": [],
    "VA": ["Vatican City"],
    "SM": ["San Marino"],
    "MC": ["Monaco"],
    "LI": ["Vaduz"],
    "AD": ["Andorra la Vella"],
    "MT": ["Valletta"],
    "CY": ["Nicosia", "Paphos"],
    "GR2": [],
    "TR2": [],
}

#: Notable peaks and special points, with their real elevation.
PEAKS = [
    ("sniezka", "Śnieżka", "PL", 50.73617, 15.73972, 1603),
    ("rysy", "Rysy", "PL", 49.18950, 19.08100, 2499),
    ("giewont", "Giewont", "PL", 49.29610, 20.06060, 1894),
    ("everest", "Mount Everest", "NP", 27.98810, 86.92500, 8849),
    ("k2", "K2", "PK", 35.88080, 76.51330, 8611),
    ("matterhorn", "Matterhorn", "CH", 45.97630, 7.65860, 4478),
    ("fuji", "Mount Fuji", "JP", 35.36060, 138.72740, 3776),
    ("kilimanjaro", "Mount Kilimanjaro", "TZ", -3.06740, 37.35560, 5895),
    ("denali", "Denali", "US", 63.06920, -151.00690, 6190),
    ("ben-nevis", "Ben Nevis", "GB", 56.79690, -5.00360, 1345),
    ("zugspitze", "Zugspitze", "DE", 47.42100, 10.98600, 2962),
    ("monte-rosa", "Monte Rosa", "CH", 45.83420, 7.85890, 4634),
    ("aconcagua", "Aconcagua", "AR", -32.65320, -70.01090, 6961),
    ("mount-blanc", "Mont Blanc", "FR", 45.83260, 6.86520, 4808),
    ("kosciuszko", "Mount Kosciuszko", "AU", -36.45530, 148.26340, 2228),
]


#: Alternative names used when the capital is spelled differently in the
#: city list.
ALIASES = {
    "El Aaiún": ["El Aaiun"],
    "St. Peter Port": ["Saint Peter Port", "St Peter Port"],
    "St. George's": ["Saint George's", "Saint Georges"],
    "City of Victoria": ["Victoria"],
    "Nur-Sultan": ["Nur Sultan", "Astana"],
    "South Tarawa": ["Tarawa"],
    "Naypyidaw": ["Nay Pyi Taw"],
    "City of San Marino": ["San Marino"],
    "Fakaofo": ["Fakaofo", "Tokelau"],
    "Washington D.C.": ["Washington", "Washington DC"],
    "Cologne": ["Koln", "Cologne"],
    "Bangalore": ["Bengaluru"],
    "Tromso": ["Tromsø", "Tromso"],
    "Heraklion": ["Irakleio", "Heraklion", "Heraklion Crete"],
    "Zanzibar City": ["Zanzibar"],
    "Victoria (Seychelles)": ["Victoria"],
    "Saint George's": ["Saint George's"],
    "Port-of-Spain": ["Port of Spain"],
    "Ngerulmud": ["Ngerulmud"],
    "Willemstad": ["Willemstad"],
    "Philipsburg": ["Philipsburg"],
    "Oranjestad": ["Oranjestad"],
    "The Valley": ["The Valley"],
    "Road Town": ["Road Town"],
    "Charlotte Amalie": ["Charlotte Amalie"],
    "Basseterre": ["Basseterre"],
    "Gustavia": ["Gustavia"],
    "Nuuk": ["Nuuk"],
    "Adamstown": ["Adamstown"],
    "Port Vila": ["Port Vila"],
    "Funafuti": ["Funafuti"],
    "Palikir": ["Palikir"],
    "Melekeok": ["Melekeok"],
    "Nuku'alofa": ["Nuku'alofa"],
    "Apia": ["Apia"],
    "Pago Pago": ["Pago Pago"],
    "Majuro": ["Majuro"],
    "Tarawa": ["Tarawa"],
}


def normalise(name: str) -> str:
    """Fold a name down to comparable letters."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", name.lower())


def slug(name: str) -> str:
    """A short, readable identifier for a place."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "place"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report the matching quality")
    parser.add_argument("--out", default=OUTPUT)
    args = parser.parse_args()

    with open("cities.json") as handle:
        cities = json.load(handle)
    with open("wc.json") as handle:
        countries = json.load(handle)

    by_country: dict[str, list[dict]] = {}
    for city in cities:
        by_country.setdefault(city.get("country", ""), []).append(city)

    def find(country_code: str, name: str) -> dict | None:
        """Best matching city for a name inside a country."""
        candidates = by_country.get(country_code, [])
        for attempt in [name] + ALIASES.get(name, []):
            target = normalise(attempt)
            exact = [c for c in candidates if normalise(c["name"]) == target]
            if exact:
                return exact[0]
            starts = [c for c in candidates if normalise(c["name"]).startswith(target)]
            if starts:
                return starts[0]
            for candidate in candidates:
                if target in normalise(candidate["name"]):
                    return candidate
        return None

    entries: list[dict] = []
    seen: set[str] = set()
    unmatched: list[str] = []

    def add(name, country_name, code, flag, latitude, longitude, elevation, kind):
        identifier = slug(name)
        while identifier in seen:
            identifier += "-2"
        seen.add(identifier)
        entries.append(
            {
                "id": identifier,
                "name": name,
                "country": country_name,
                "country_code": code,
                "flag": flag,
                "latitude": round(float(latitude), 5),
                "longitude": round(float(longitude), 5),
                "elevation": int(elevation) if elevation is not None else None,
                "kind": kind,
            }
        )

    # Capitals.
    for country in countries:
        code = country.get("cca2")
        if not code or not country.get("capital"):
            continue
        flag = country.get("flag") or ""
        name = country["capital"][0]
        match = find(code, name)
        if match is None:
            unmatched.append(f"{name} ({code})")
            lat, lon = country.get("latlng", [0, 0])
            add(name, country["name"]["common"], code, flag, lat, lon, None, "capital")
            continue
        add(
            name,
            country["name"]["common"],
            code,
            flag,
            match["lat"],
            match["lng"],
            None,
            "capital",
        )

    # Major cities.
    for code, names in EXTRA.items():
        if not code or not names:
            continue
        country = next((c for c in countries if c.get("cca2") == code), None)
        if country is None:
            continue
        for name in names:
            match = find(code, name)
            if match is None:
                unmatched.append(f"{name} ({code})")
                continue
            add(
                name,
                country["name"]["common"],
                code,
                country.get("flag") or "",
                match["lat"],
                match["lng"],
                None,
                "city",
            )

    # Peaks.
    for identifier, name, code, lat, lon, elevation in PEAKS:
        country = next((c for c in countries if c.get("cca2") == code), None)
        add(
            name,
            country["name"]["common"] if country else code,
            code,
            country.get("flag") if country else "",
            lat,
            lon,
            elevation,
            "peak",
        )

    print(f"{len(entries)} places, {len(unmatched)} unmatched")
    if unmatched:
        print("  unmatched:", ", ".join(unmatched[:20]))

    if args.check:
        return 0

    with open(args.out, "w") as handle:
        handle.write("# World places for the widget.\n")
        handle.write("# Generated by build_places.py, do not edit by hand.\n")
        handle.write("places:\n")
        for entry in sorted(entries, key=lambda e: (e["country"], e["name"])):
            handle.write(f"  - id: {entry['id']}\n")
            handle.write(f"    name: {entry['name']}\n")
            handle.write(f"    country: {entry['country']}\n")
            handle.write(f"    country_code: {entry['country_code']}\n")
            handle.write(f"    latitude: {entry['latitude']}\n")
            handle.write(f"    longitude: {entry['longitude']}\n")
            handle.write(f"    elevation: {entry['elevation'] if entry['elevation'] is not None else 'null'}\n")
            handle.write(f"    flag: {entry['flag'] or ''}\n")
            handle.write(f"    kind: {entry['kind']}\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
