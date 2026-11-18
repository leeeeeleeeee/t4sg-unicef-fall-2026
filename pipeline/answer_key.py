"""Build the UNICEF benchmark answer key from prompts/*.csv.

Each input row supplies `indicator_code` (UNICEF) and
`datacommons_variable_id` (UN System Data Commons). No code discovery or
hard-coded indicator mapping is performed here.

Install: python -m pip install requests
Run:     python pipeline/answer_key.py
         python pipeline/answer_key.py --check
         python pipeline/answer_key.py --id N1
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"
OUTFILE = ROOT / "data" / "answer_key.csv"
COVERAGE_FILE = ROOT / "data" / "missing_data_report.csv"
UNICEF_BASE = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest/data/UNICEF,GLOBAL_DATAFLOW,1.0"
DC_URL = "https://unsd-datacommons.gcp.un-icc.cloud/core/api/v2/observation"
COLUMNS = ["id", "unicef_value", "datacommons_value", "year", "range_low", "range_high", "unit", "source", "data_exists", "lag_flag"]
FEMALE_PROMPT_IDS = {"N3", "R3", "P3"}
COVERAGE_COLUMNS = ["id", "country_code", "requested_year", "unicef_status", "unicef_reason", "datacommons_status", "datacommons_reason"]


def load_prompts():
    prompts = []
    for path in [PROMPTS_DIR / "prompts.csv"]:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            required = {"id", "prompt", "country_code", "indicator_code", "year", "datacommons_variable_id"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{path.name}: missing columns: {sorted(missing)}")
            for row in reader:
                if row.get("id", "").strip():
                    prompts.append({key: (value or "").strip() for key, value in row.items() if key})
    if not prompts:
        raise ValueError("No prompts found in prompts/*.csv")
    ids = [p["id"] for p in prompts]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        raise ValueError(f"Duplicate prompt IDs: {duplicates}. Remove backup CSVs from prompts/.")
    return prompts


def num(raw):
    if raw is None or str(raw).strip().lower() in {"", "na", "n/a", "null", ".."}:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_year(raw) -> int | None:
    match = re.match(r"^\s*(\d{4})", str(raw or ""))
    return int(match.group(1)) if match else None


def target_year(prompt: dict) -> int | None:
    return parse_year(prompt.get("year", ""))


def format_years(years: list[int]) -> str:
    if not years:
        return "none"
    years = sorted(set(years))
    if len(years) <= 12:
        return ", ".join(map(str, years))
    return f"{years[0]}–{years[-1]} ({len(years)} years; most recent: {', '.join(map(str, years[-5:]))})"


def requested_subgroup(prompt: dict) -> str:
    """Explicit subgroup requests. Never substitute a national total."""
    pid = prompt.get("id", "")
    if pid == "T2-4":
        return "sex_gap"
    if pid in FEMALE_PROMPT_IDS:
        return "female"
    if pid == "T2-5":
        return "urban"
    if pid == "T3-3":
        return "rural"
    return "total"


def _sex_matches(item: dict, group: str) -> bool:
    sex = item.get("SEX", "").upper()
    if group == "female":
        return sex in {"F", "FEMALE"}
    if group == "male":
        return sex in {"M", "MALE"}
    return sex in {"", "_T", "T", "TOTAL"}


def _residence_matches(item: dict, group: str) -> bool:
    """Match an explicit residence field; fail closed if none exists.

    SDMX uses different dimensions across indicators. These names/codes are
    common candidates, not a guarantee for any specific series. If a response
    lacks an appropriate dimension, it must be reviewed rather than guessing.
    """
    keys = ("RESIDENCE", "URBAN_RURAL", "URBANIZATION", "LOCATION", "AREA_TYPE", "SETTLEMENT")
    expected = ({"U", "URB", "URBAN"} if group == "urban"
                else {"R", "RUR", "RURAL"})
    return any(item.get(k, "").upper() in expected for k in keys)


def get_unicef(session: requests.Session, prompt: dict) -> dict:
    country = prompt.get("country_code", "")
    indicator = prompt.get("indicator_code", "")
    if not country or not indicator:
        return {"status": "unmapped", "note": "Missing country_code or indicator_code"}
    if not re.fullmatch(r"[A-Za-z]{3}", country) or not re.fullmatch(r"[A-Za-z0-9_-]+", indicator):
        return {"status": "invalid_mapping", "note": "Invalid country or indicator code format"}

    # Same SDMX global dataflow as the team's original NGA.CME_MRY0T4._T
    # example, but without hard-coding sex, because some prompts need girls.
    url = f"{UNICEF_BASE}/{country}.{indicator}."
    try:
        response = session.get(url, params={"format": "csv", "labels": "id"}, timeout=35)
        if response.status_code == 404 and "No data for data query" in response.text:
            return {"status": "no_observations", "note": "No matching observations in UNICEF global dataflow", "years": []}
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"status": "api_error", "note": f"{type(exc).__name__}: {exc}"}

    reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
    fields = {f.strip().upper() for f in (reader.fieldnames or []) if f}
    if not {"TIME_PERIOD", "OBS_VALUE"}.issubset(fields):
        return {"status": "parse_error", "note": "UNICEF response lacks TIME_PERIOD or OBS_VALUE columns"}

    group = requested_subgroup(prompt)
    records: list[dict] = []
    raw_years = set()
    dimensions_seen = set()
    for raw in reader:
        item = {str(k or "").strip().upper(): str(v or "").strip() for k, v in raw.items()}
        yr, value = parse_year(item.get("TIME_PERIOD")), num(item.get("OBS_VALUE"))
        if yr is None or value is None:
            continue
        if item.get("REF_AREA", "") not in ("", country) or item.get("INDICATOR", "") not in ("", indicator):
            continue
        raw_years.add(yr)
        dimensions_seen.update(k for k,v in item.items() if v and k in
                               {"RESIDENCE", "URBAN_RURAL", "URBANIZATION", "LOCATION", "AREA_TYPE", "SETTLEMENT"})
        if group in {"total", "female"} and not _sex_matches(item, group):
            continue
        if group == "sex_gap" and not (_sex_matches(item, "male") or _sex_matches(item, "female")):
            continue
        if group in {"urban", "rural"} and not _residence_matches(item, group):
            continue
        if group in {"urban", "rural"} and not _sex_matches(item, "total"):
            continue
        records.append({
            "year": yr, "value": value,
            "sex": item.get("SEX", "").upper(),
            "low": num(item.get("LOWER_BOUND") or item.get("LOWER_CI") or item.get("OBS_LOW")),
            "high": num(item.get("UPPER_BOUND") or item.get("UPPER_CI") or item.get("OBS_HIGH")),
            "unit": item.get("UNIT_MEASURE") or item.get("UNIT") or "",
            "source": item.get("SOURCE") or item.get("SOURCE_DETAIL") or item.get("DATA_SOURCE") or "UNICEF SDMX",
            "dimensions": tuple(sorted((k,v) for k,v in item.items() if v and k in
                                       {"SEX", "AGE", "RESIDENCE", "URBAN_RURAL", "URBANIZATION", "LOCATION", "AREA_TYPE", "SETTLEMENT"}))
        })
    years = sorted({r["year"] for r in records})
    if not records:
        if group in {"urban", "rural"} and raw_years:
            return {"status": "subgroup_unavailable", "note": f"No explicit {group} breakdown in returned series; available dimensions: {sorted(dimensions_seen) or 'none'}", "years": sorted(raw_years)}
        return {"status": "no_observations", "note": f"No matching numerical observations for requested subgroup ({group})", "years": sorted(raw_years)}

    requested = target_year(prompt)
    matching = [r for r in records if requested is None or r["year"] == requested]
    if not matching:
        return {"status": "missing_year", "note": f"Requested {requested} not available for {group}; no year substituted", "years": years}
    chosen_year = max(r["year"] for r in matching)
    candidates = [r for r in matching if r["year"] == chosen_year]

    if group == "sex_gap":
        female = [r for r in candidates if r["sex"] in {"F", "FEMALE"}]
        male = [r for r in candidates if r["sex"] in {"M", "MALE"}]
        if not female or not male:
            return {"status": "subgroup_unavailable", "note": "Cannot calculate gap: missing male or female series", "years": years}
        if len({(r["value"], r["unit"], r["dimensions"]) for r in female}) != 1 or len({(r["value"], r["unit"], r["dimensions"]) for r in male}) != 1:
            return {"status": "ambiguous_series", "note": "Multiple male or female series; review dimensions", "years": years}
        f, m = female[0], male[0]
        if f["unit"] != m["unit"] or f["unit"].upper() not in {"PCNT", "PERCENT", "%"}:
            return {"status": "ambiguous_series", "note": f"Cannot safely compute percentage-point gap with units {f['unit']} / {m['unit']}", "years": years}
        return {"status": "ok", "value": round(f["value"] - m["value"], 8), "year": chosen_year,
                "low": None, "high": None, "unit": "percentage points", "source": f["source"] if f["source"] == m["source"] else "UNICEF SDMX",
                "years": years, "note": f"Calculated female minus male: {f['value']}% - {m['value']}%; signed percentage-point difference"}

    # Distinct subseries with different values (or age classifications) are
    # not interchangeable; ask for a review instead of silently selecting.
    unique = {(r["value"], r["unit"], r["dimensions"]) for r in candidates}
    if len(unique) > 1:
        return {"status": "ambiguous_series", "note": f"{len(candidates)} distinct rows for {chosen_year}; inspect dimensions", "years": years}
    selected = candidates[0]
    return {"status": "ok", "value": selected["value"], "year": chosen_year,
            "low": selected["low"], "high": selected["high"], "unit": selected["unit"],
            "source": selected["source"], "years": years, "note": ""}


def _dc_query(session: requests.Session, stat_var: str, entity: str,
              year: int | None, facet_id: str = "") -> dict:
    """Query UN System Data Commons for observations, not just availability.

    Both `select=date` and `select=value` are mandatory. This was the reason
    the original probe returned an empty byEntity object despite HTTP 200.
    """
    params = [
        ("entity.dcids", entity),
        ("variable.dcids", stat_var),
        ("date", ""),
        ("select", "date"),
        ("select", "value"),
        ("select", "facet"),
    ]
    if facet_id:
        params.append(("filter.facet_ids", facet_id))
    try:
        response = session.get(DC_URL, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"status": "api_error", "stat_var": stat_var,
                "note": f"{type(exc).__name__}: {exc}"}
    if not isinstance(payload, dict):
        return {"status": "parse_error", "stat_var": stat_var,
                "note": "Expected JSON object"}
    node = payload.get("byVariable", {}).get(stat_var, {}).get("byEntity", {}).get(entity, {})
    metadata = payload.get("facets", {})
    records = []
    for facet in node.get("orderedFacets", []):
        fid = str(facet.get("facetId", ""))
        properties = metadata.get(fid, {})
        for obs in facet.get("observations", []):
            yr, value = parse_year(obs.get("date")), num(obs.get("value"))
            if yr is not None and value is not None:
                records.append({"year": yr, "value": value, "facet": fid,
                                "source": properties.get("provenanceUrl", ""),
                                "unit": properties.get("unit", "")})
    if not records:
        return {"status": "no_observations", "stat_var": stat_var,
                "note": "No numerical observations returned"}
    candidates = [r for r in records if year is None or r["year"] == year]
    if not candidates:
        return {"status": "missing_year", "stat_var": stat_var,
                "note": f"Requested {year}; available: {format_years([r['year'] for r in records])}"}
    latest = max(r["year"] for r in candidates)
    candidates = [r for r in candidates if r["year"] == latest]
    distinct = {(r["value"], r["unit"]) for r in candidates}
    if len(distinct) > 1:
        return {"status": "ambiguous_facets", "stat_var": stat_var,
                "note": f"{len(candidates)} observations across facets for {latest}; review provenance"}
    # Multiple facets with identical value/unit can be used for the comparison.
    selected = sorted(candidates, key=lambda r: r["facet"])[0]
    return {"status": "ok", "stat_var": stat_var, **selected, "note": ""}




def get_datacommons(session, prompt):
    """Retrieve exactly the DCID provided by the prompt CSV."""
    stat_var = prompt.get("datacommons_variable_id", "")
    country = prompt.get("country_code", "")
    if not stat_var or not country:
        return {"status": "unmapped", "note": "Missing Data Commons variable ID or country"}
    if not re.fullmatch(r"[A-Za-z]{3}", country):
        return {"status": "invalid_mapping", "note": "Invalid country code"}

    group = requested_subgroup(prompt)
    year = target_year(prompt)
    entity = f"country/{country}"

    # Optional format for calculated percentage-point gaps:
    #     female_variable_id | male_variable_id
    if group == "sex_gap":
        ids = [v.strip() for v in stat_var.split("|") if v.strip()]
        if len(ids) != 2:
            return {"status": "unmapped", "note": "Sex gap needs 'female DCID | male DCID'"}
        female = _dc_query(session, ids[0], entity, year)
        male = _dc_query(session, ids[1], entity, year)
        if female.get("status") != "ok" or male.get("status") != "ok":
            return {"status": "no_observations", "note": f"Female: {female['status']}; male: {male['status']}"}
        if female["year"] != male["year"] or female["unit"] != male["unit"] or not dc_percent(female["unit"]):
            return {"status": "ambiguous_series", "note": "Sex-gap series have incompatible years or units"}
        return {"status": "ok", "value": female["value"] - male["value"],
                "year": female["year"], "unit": "percentage points", "source": female.get("source", "")}

    if "|" in stat_var:
        return {"status": "invalid_mapping", "note": "Multiple DCIDs only supported for the sex-gap prompt"}
    if group == "female" and "SEX--F" not in stat_var.upper():
        return {"status": "invalid_mapping", "note": "Female prompt requires an explicitly female DCID"}
    if group in {"urban", "rural"}:
        suffixes = ("URBAN", "--U") if group == "urban" else ("RURAL", "--R")
        if not any(s in stat_var.upper() for s in suffixes):
            return {"status": "invalid_mapping", "note": f"{group} prompt requires an explicit {group} DCID"}
    if group == "total" and re.search(r"SEX--(?:F|M)(?:__|$)", stat_var.upper()):
        return {"status": "invalid_mapping", "note": "Total-population prompt has sex-specific DCID"}
    return _dc_query(session, stat_var, entity, year)


def dc_percent(unit):
    unit = (unit or "").upper()
    return "PCNT" in unit or "PERCENT" in unit


def units_compatible(u_unit, d_unit):
    """Fail closed if units cannot be established as the same."""
    u = (u_unit or "").upper()
    d = (d_unit or "").upper()
    if not u or not d:
        return False
    if u in {"PCNT", "%", "PERCENT"}:
        return dc_percent(d)
    if u == "PERCENTAGE POINTS":
        return d == "PERCENTAGE POINTS"
    if u in {"PER_1000_LIVE_BIRTHS", "RATIO_COUNT_DEATHS_PER_1000_COUNT_LIVEBIRTHS"}:
        return "DEATHS_PER_1000" in d and "LIVEBIRTHS" in d
    # Other SDMX unit codes require explicit interpretation before comparison.
    return False


def output_row(prompt, u, d):
    u_ok, d_ok = u.get("status") == "ok", d.get("status") == "ok"
    # A single year field follows the UNICEF record when available.
    year = u.get("year") if u_ok else d.get("year") if d_ok else ""
    # A lag can only be established by comparing observations from BOTH APIs.
    # Missing Data Commons data must never be interpreted as a disagreement.
    lag_flag = ""
    if u_ok and d_ok:
        same_year = u.get("year") == d.get("year")
        same_units = units_compatible(u.get("unit"), d.get("unit"))
        if same_year and same_units:
            tolerance = max(1e-5, abs(u["value"]) * 1e-4)
            lag_flag = "true" if abs(u["value"] - d["value"]) > tolerance else "false"
    # Otherwise leave lag_flag blank: one/both values missing or incomparable.

    if u_ok or d_ok:
        data_exists = "true"
    elif u.get("status") in {"missing_year", "no_observations", "subgroup_unavailable"} and d.get("status") in {"missing_year", "no_observations"}:
        data_exists = "false"  # UNICEF confirmed no requested observation
    else:
        data_exists = ""  # Mapping/API error: absence not established

    return {
        "id": prompt["id"],
        "unicef_value": u.get("value") if u_ok else "",
        "datacommons_value": d.get("value") if d_ok else "",
        "year": year,
        "range_low": u.get("low") if u_ok and u.get("low") is not None else "",
        "range_high": u.get("high") if u_ok and u.get("high") is not None else "",
        "unit": u.get("unit", "") if u_ok else d.get("unit", "") if d_ok else "",
        "source": u.get("source", "") if u_ok else d.get("source", "") if d_ok else "",
        "data_exists": data_exists,
        "lag_flag": lag_flag,
    }


def missing_record(prompt: dict, unicef: dict, dc: dict) -> dict | None:
    """Return a report row only if at least one source lacks usable data.

    A missing mapping or a failed API request is unresolved, NOT proof of
    missing source coverage. Keep the underlying status and reason visible.
    """
    us, ds = unicef.get("status", "unknown"), dc.get("status", "unknown")
    if us == "ok" and ds == "ok":
        return None

    def reason(result, status):
        if status == "ok":
            return ""
        detail = result.get("note") or status
        years = result.get("years") or []
        if status == "missing_year" and years:
            detail += f"; available: {format_years(years)}"
        return detail

    return {
        "id": prompt["id"],
        "country_code": prompt.get("country_code", ""),
        "requested_year": prompt.get("year", "") or "latest",
        "unicef_status": us,
        "unicef_reason": reason(unicef, us),
        "datacommons_status": ds,
        "datacommons_reason": reason(dc, ds),
    }


def write_coverage(records: list[dict]) -> None:
    """Write only prompts with missing/unresolved data, never successful pairs."""
    COVERAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with COVERAGE_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COVERAGE_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description="Generate answer key and report prompts missing either API observation")
    parser.add_argument("--check", action="store_true", help="Check that prompt identifiers exist")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--show-years", action="store_true")
    parser.add_argument("--preflight-only", action="store_true", help="Only write data/missing_data_report.csv")
    parser.add_argument("--covered-only", action="store_true", help="Only output rows with confirmed Data Commons observations")
    args = parser.parse_args()

    prompts = load_prompts()
    print(f"Loaded {len(prompts)} question(s).")
    if args.check:
        for p in prompts:
            missing = [c for c in ("country_code", "indicator_code", "datacommons_variable_id") if not p.get(c)]
            if missing:
                print(f"REVIEW {p['id']}: missing {', '.join(missing)}")
        return
    if args.ids:
        wanted = set(args.ids)
        prompts = [p for p in prompts if p["id"] in wanted]
    if args.limit is not None:
        prompts = prompts[:args.limit]

    # Check BOTH sources once and reuse the results to build the answer key.
    # Only missing/unresolved prompts appear in the report and on screen.
    with requests.Session() as session:
        results = []
        missing = []
        for prompt in prompts:
            u = get_unicef(session, prompt)
            d = get_datacommons(session, prompt)
            results.append((prompt, u, d))
            issue = missing_record(prompt, u, d)
            if issue is not None:
                missing.append(issue)
                print(f"{prompt['id']}:")
                if u.get("status") != "ok":
                    print(f"  UNICEF [{u.get('status')}]: {issue['unicef_reason']}")
                if d.get("status") != "ok":
                    print(f"  Data Commons [{d.get('status')}]: {issue['datacommons_reason']}")
                if args.show_years:
                    for name, result in (("UNICEF", u), ("Data Commons", d)):
                        if result.get("years"):
                            print(f"  {name} available years: {format_years(result['years'])}")

    write_coverage(missing)
    print(f"Checked {len(prompts)} prompts: {len(missing)} with missing/unresolved data; "
          f"{len(prompts) - len(missing)} with values from both APIs.")
    print(f"Missing-data report: {COVERAGE_FILE}")
    if args.preflight_only:
        return

    selected = [item for item in results if item[2].get("status") == "ok"] if args.covered_only else results
    rows = [output_row(p, u, d) for p, u, d in selected]
    OUTFILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTFILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {OUTFILE}")
    print("Unresolved mappings and API errors are not proof that official data is absent.")


if __name__ == "__main__":
    main()
