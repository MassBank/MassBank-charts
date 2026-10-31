#!/usr/bin/env python3
"""Check previously observed API differences against source records, not another API."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from itertools import islice
import json
from pathlib import Path
import re

from compare_apis import Client, differences


DATE_PATTERN = re.compile(
    r"(\d{4}\.\d{2}\.\d{2})"
    r"(?: \(Created (\d{4}\.\d{2}\.\d{2})(?:, modified (\d{4}\.\d{2}\.\d{2}))?\))?"
)


def source_date(value):
    match = DATE_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid source DATE: {value!r}")
    return {
        name: datetime.strptime(part, "%Y.%m.%d").date().isoformat()
        for name, part in zip(("updated", "created", "modified"), match.groups())
        if part is not None
    }


def primary_fields(text):
    fields = {}
    peaks = []
    in_peaks = False
    for line in text.splitlines():
        if line == "//":
            break
        if in_peaks:
            values = line.split()
            if len(values) != 3:
                raise ValueError(f"Invalid source peak row: {line!r}")
            peaks.append([Decimal(value) for value in values])
        elif line.startswith("PK$PEAK: "):
            fields["peak_header"] = line.removeprefix("PK$PEAK: ").split()
            in_peaks = True
        elif ": " in line:
            tag, value = line.split(": ", 1)
            fields.setdefault(tag, []).append(value)
    if "DEPRECATED" in fields:
        raise ValueError("Source record is deprecated in this snapshot")
    if len(fields.get("DATE", [])) != 1 or not in_peaks:
        raise ValueError("Source record must contain one DATE and a PK$PEAK section")
    classes = fields.get("CH$COMPOUND_CLASS", [])
    return {
        "date": source_date(fields["DATE"][0]),
        "copyright": fields.get("COPYRIGHT", [""])[0],
        "compound_classes": [item for value in classes for item in value.split("; ")],
        "peak_header": fields["peak_header"],
        "peak_count": int(fields["PK$NUM_PEAK"][0]),
        "peaks": peaks,
    }


def api_fields(record):
    peak = record["peak"]
    return {
        "date": record["date"],
        "copyright": record.get("copyright", ""),
        "compound_classes": record["compound"].get("classes", []),
        "peak_header": peak["peak"].get("header", []),
        "peak_count": peak["numPeak"],
        "peaks": [
            [Decimal(str(row[key])) if key in row else "<missing>" for key in ("mz", "intensity", "rel")]
            for row in peak["peak"]["values"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--source-reference", required=True, help="Snapshot commit/release for the report")
    parser.add_argument("--sample-report", type=Path, required=True, help="compare_apis.py report supplying accession samples")
    parser.add_argument("--accession", action="append", default=[], help="Additional accession; may be repeated")
    parser.add_argument("--old", default="https://msbi.ipb-halle.de/MassBank-api")
    parser.add_argument("--new", default="https://msbi.ipb-halle.de/MassBank3-api")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sample = json.loads(args.sample_report.read_text())
    accessions = list(dict.fromkeys(sample["sample_accessions"] + args.accession))
    if not accessions:
        parser.error("No accessions selected")
    selected = set(accessions)
    paths = {}
    for path in args.source_data.rglob("*.txt"):
        if path.stem in selected:
            if path.stem in paths:
                raise ValueError(f"Duplicate source accession: {path.stem}")
            paths[path.stem] = path
    sources = {}
    source_hashes = {}
    for accession in accessions:
        if not re.fullmatch(r"MSBNK-[A-Za-z0-9_]+-[A-Za-z0-9_]+", accession):
            raise ValueError(f"Invalid accession: {accession!r}")
        if accession not in paths:
            raise FileNotFoundError(f"Missing source accession: {accession}")
        content = paths[accession].read_bytes()
        sources[accession] = primary_fields(content.decode("utf-8"))
        source_hashes[accession] = hashlib.sha256(content).hexdigest()
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_reference": args.source_reference,
        "source_data": str(args.source_data),
        "sample_report": str(args.sample_report),
        "apis": {"old": args.old, "new": args.new},
        "scope": "DATE, copyright, compound classes, peak header/count and all numeric peak values of each sampled full record",
        "methodology": "Missing historical dates are omitted; dates use ISO date-only format. Class lists follow '; ' source separators. Peak IDs are database identifiers, not source values. Peak order and decimal numeric equality are preserved, without rounding tolerance. Within differences, 'old' means source and 'new' means the API response. This is not a full-field or exhaustive-record audit.",
        "caveat": "The local snapshot may be newer than the deployed release; source mismatches require checking the deployed raw-text record before attributing them to conversion.",
        "cases": [],
    }
    clients = {
        side: Client(url, timeout=60, delay=0.1, max_bytes=16 * 1024 * 1024)
        for side, url in report["apis"].items()
    }
    try:
        for accession in accessions:
            expected = sources[accession]
            case = {
                "accession": accession, "source_file": str(paths[accession]),
                "source_sha256": source_hashes[accession], "source_date": expected["date"],
            }
            for side, client in clients.items():
                response = client.get(f"/records/{accession}")
                result = {"response": response.summary()}
                if response.error:
                    result["error"] = response.error
                else:
                    actual = api_fields(response.data)
                    result["matching_fields"] = [key for key in expected if expected[key] == actual[key]]
                    result["differing_fields"] = [key for key in expected if expected[key] != actual[key]]
                    changes = list(islice(differences(expected, actual), 21))
                    result["differences"] = changes[:20]
                    result["differences_truncated"] = len(changes) > 20
                case[side] = result
            report["cases"].append(case)
    finally:
        for client in clients.values():
            client.close()
    report["summary"] = {
        side: {
            "checked": len(report["cases"]),
            "matching": sum(not case[side].get("error") and not case[side]["differing_fields"] for case in report["cases"]),
            "errors": sum(bool(case[side].get("error")) for case in report["cases"]),
            "mismatches_by_field": {
                field: sum(field in case[side].get("differing_fields", []) for case in report["cases"])
                for field in ("date", "copyright", "compound_classes", "peak_header", "peak_count", "peaks")
            },
        }
        for side in clients
    }
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report["summary"], indent=2))
    return int(any(summary["matching"] != summary["checked"] for summary in report["summary"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
