"""GeoNames gazetteer dumps: place coordinates, elevation and IANA time zone for venue cities.

Source: https://download.geonames.org/export/dump/ (free, no key, CC BY 4.0; credit "GeoNames").
Two files, downloaded once and kept under RAW_DIR/geonames/ (re-download only with `--refresh`):
- `cities500.zip`: every populated place in the world with population >= 500 (non-US venues:
  Bahamas, Mexico, Europe, Canada, Caribbean; and most US cities).
- `US.zip`: every US feature; only populated places (feature class P) are used, for the small
  college towns and campus CDPs that cities500 lacks (e.g. Storrs, Villanova).

Each row is one place: `latitude`/`longitude` (WGS84), `elevation` (m, often empty) and `dem` (m,
SRTM3/GTOPO30 at the point), `timezone` (IANA). Coordinates are the place's, not the arena's: a
venue gets its city's point (within a few km; elevation within tens of metres for most towns).

Everything below `fetch` is pure: parsers take text lines, matchers take parsed rows.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.http import PoliteClient

BASE_URL = "https://download.geonames.org/export/dump"
FILES = ("cities500", "US")

# Columns of the GeoNames "geoname" table (readme.txt in the dump directory).
COLUMNS = (
    "geonameid",
    "name",
    "asciiname",
    "alternatenames",
    "latitude",
    "longitude",
    "feature_class",
    "feature_code",
    "country_code",
    "cc2",
    "admin1_code",
    "admin2_code",
    "admin3_code",
    "admin4_code",
    "population",
    "elevation",
    "dem",
    "timezone",
    "modification_date",
)

# ESPN writes a US venue's state as its USPS code and a foreign venue's "state" as a province
# code or a country name. Map those to (GeoNames country code, admin1 code or None = any).
# Canadian admin1 codes are GeoNames' numeric ones.
_US = "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ"
US_STATES = (_US + " NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split(" ")
REGIONS: dict[str, tuple[str, str | None]] = {s: ("US", s) for s in US_STATES}
REGIONS.update(
    {
        "AB": ("CA", "01"),
        "BC": ("CA", "02"),
        "MB": ("CA", "03"),
        "NB": ("CA", "04"),
        "NS": ("CA", "07"),
        "ON": ("CA", "08"),
        "PQ": ("CA", "10"),
        "QC": ("CA", "10"),
        "Puerto Rico": ("PR", None),
        "PR": ("PR", None),
        "Virgin Islands": ("VI", None),
        "VI": ("VI", None),
        "Guam": ("GU", None),
        "Bahamas": ("BS", None),
        "Mexico": ("MX", None),
        "Jamaica": ("JM", None),
        "Cayman Islands": ("KY", None),
        "Dominican Republic": ("DO", None),
        "Costa Rica": ("CR", None),
        "Canada": ("CA", None),
        "England": ("GB", None),
        "Scotland": ("GB", None),
        "Northern Ireland": ("GB", None),
        "United Kingdom": ("GB", None),
        "Ireland": ("IE", None),
        "Italy": ("IT", None),
        "France": ("FR", None),
        "Spain": ("ES", None),
        "Germany": ("DE", None),
        "Greece": ("GR", None),
        "Australia": ("AU", None),
        "VIC": ("AU", "07"),
        "NSW": ("AU", "02"),
        "Japan": ("JP", None),
        "China": ("CN", None),
        "Philippines": ("PH", None),
        "Israel": ("IL", None),
    }
)

BIG_CITY = 500_000

# Venue cities the name lookup gets wrong or can't find: (ESPN city, ESPN state) -> geonameid.
# Reviewed by hand; add a row when `deepsports venues status` lists an unmatched or suspect city.
PLACE_OVERRIDES: dict[tuple[str, str], int] = {
    ("Maui", "HI"): 5849996,  # ESPN's city for the Lahaina Civic Center (Maui Invitational)
    ("Morehead", "KY"): 4301307,  # Morehead State's town (Rowan County), not the western-KY one
    ("San Juan", ""): 4568127,  # NBA preseason in Puerto Rico, listed with no state
}
# Venues far from their city's point, by ESPN venue id -> geonameid of a closer place.
VENUE_OVERRIDES: dict[str, int] = {
    # Air Force's Clune Arena: ESPN says Colorado Springs (1,832 m at the city's point); the
    # Academy (CDP "Air Force Academy") sits at ~2,070 m, the arena itself at ~2,180 m
    "2014": 7260752,
}


def fetch(
    client: PoliteClient, raw_dir: Path | None = None, refresh: bool = False
) -> list[tuple[Path, bool]]:
    """Download the dumps (one request each). Returns [(zip path, fetched now)]."""
    out_dir = (raw_dir or config.RAW_DIR) / "geonames"
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for name in FILES:
        path = out_dir / f"{name}.zip"
        if path.exists() and not refresh:
            done.append((path, False))
            continue
        body = client.get_bytes(f"{BASE_URL}/{name}.zip")
        zipfile.ZipFile(io.BytesIO(body)).testzip()  # a truncated body fails here, not later
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        done.append((path, True))
    return done


def zip_lines(path: Path) -> Iterator[str]:
    """Text lines of the .txt member of a GeoNames dump zip."""
    name = path.stem + ".txt"
    with zipfile.ZipFile(path) as z, z.open(name) as f:
        yield from io.TextIOWrapper(f, encoding="utf-8")


def _int(v: str) -> int | None:
    v = v.strip()
    return int(v) if v and v.lstrip("-").isdigit() else None


def parse_places(lines: Iterable[str], populated_only: bool = True) -> list[dict[str, Any]]:
    """GeoNames rows -> dicts. `populated_only` keeps feature class P (cities, towns, CDPs)."""
    rows = []
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if len(f) < len(COLUMNS):
            continue
        r = dict(zip(COLUMNS, f, strict=False))
        if populated_only and r["feature_class"] != "P":
            continue
        dem = _int(r["dem"])
        rows.append(
            {
                "geonameid": int(r["geonameid"]),
                "name": r["name"],
                "asciiname": r["asciiname"],
                "alternatenames": [a for a in r["alternatenames"].split(",") if a],
                "lat": float(r["latitude"]),
                "lon": float(r["longitude"]),
                "feature_code": r["feature_code"],
                "country": r["country_code"],
                "admin1": r["admin1_code"],
                "population": _int(r["population"]) or 0,
                "elevation": _int(r["elevation"]),
                "dem": None if dem is None or dem <= -9999 else dem,
                "timezone": r["timezone"] or None,
            }
        )
    return rows


def norm(name: str | None) -> str:
    """Comparable place name: ASCII, lower case, 'St.'/'Ste.'/'Mt.'/'Ft.' spelled out, no
    punctuation or spaces."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\bste\.?\s", "sainte ", s)
    s = re.sub(r"\bst\.?\s", "saint ", s)
    s = re.sub(r"\bmt\.?\s", "mount ", s)
    s = re.sub(r"\bft\.?\s", "fort ", s)
    return re.sub(r"[^a-z0-9]", "", s)


class Gazetteer:
    """Index of parsed places by (country, admin1, normalized name)."""

    def __init__(self, places: Iterable[dict[str, Any]]):
        self.primary: dict[tuple[str, str, str], list[dict]] = {}
        self.alternate: dict[tuple[str, str, str], list[dict]] = {}
        seen: set[int] = set()
        for p in places:
            if p["geonameid"] in seen:  # cities500 and US.zip overlap
                continue
            seen.add(p["geonameid"])
            names = {norm(p["name"]), norm(p["asciiname"])}
            for n in names:
                self.primary.setdefault((p["country"], p["admin1"], n), []).append(p)
            for n in {norm(a) for a in p["alternatenames"]} - names:
                self.alternate.setdefault((p["country"], p["admin1"], n), []).append(p)
        self.by_id = {p["geonameid"]: p for ps in self.primary.values() for p in ps}
        # big cities by name alone, for venues ESPN lists with no state (NBA games abroad)
        self.big: dict[str, list[dict]] = {}
        for p in self.by_id.values():
            if p["population"] >= BIG_CITY:
                for n in {norm(p["name"]), norm(p["asciiname"])}:
                    self.big.setdefault(n, []).append(p)
        self._admins: dict[str, set[str]] = {}
        for c, a, _ in self.primary:
            self._admins.setdefault(c, set()).add(a)

    def _lookup(self, index: dict, country: str, admin1: str | None, name: str) -> list[dict]:
        admins = [admin1] if admin1 is not None else sorted(self._admins.get(country, ()))
        return [p for a in admins for p in index.get((country, a, name), [])]

    def match(
        self, city: str | None, state: str | None, venue_id: str | None = None
    ) -> tuple[dict | None, str]:
        """(best place or None, how): how is 'venue_override', 'override', 'name', 'alternate',
        'big_city' (no state given: the most populous city of that name anywhere, if >= BIG_CITY
        people) or
        why it failed ('no city', 'no state', 'unknown region', 'no match'). Ties go to the most
        populous place."""
        if VENUE_OVERRIDES.get(venue_id or "") in self.by_id:
            return self.by_id[VENUE_OVERRIDES[venue_id]], "venue_override"
        if not city:
            return None, "no city"
        override = PLACE_OVERRIDES.get((city, state or ""))
        if override in self.by_id:
            return self.by_id[override], "override"
        if not state:
            hits = self.big.get(norm(city))
            if hits:
                return max(hits, key=lambda p: (p["population"], -p["geonameid"])), "big_city"
            return None, "no state"
        region = REGIONS.get(state.strip())
        if region is None:
            return None, "unknown region"
        country, admin1 = region
        for how, index in (("name", self.primary), ("alternate", self.alternate)):
            hits = self._lookup(index, country, admin1, norm(city))
            if hits:
                return max(hits, key=lambda p: (p["population"], -p["geonameid"])), how
        return None, "no match"


def elevation_m(place: dict[str, Any]) -> int | None:
    """The place's stated elevation if GeoNames has one, else the DEM value at its point."""
    return place["elevation"] if place["elevation"] is not None else place["dem"]


def load_gazetteer(raw_dir: Path | None = None) -> Gazetteer:
    base = (raw_dir or config.RAW_DIR) / "geonames"
    places: list[dict[str, Any]] = []
    for name in FILES:
        path = base / f"{name}.zip"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: run `deepsports venues fetch` first")
        places += parse_places(zip_lines(path))
    return Gazetteer(places)
