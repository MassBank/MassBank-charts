#!/usr/bin/env python3
"""Check previously observed API differences against source records, not another API."""

import argparse
from collections import Counter
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


def primary_fields(text, all_fields=False):
    fields = {}
    peaks = []
    annotation_header = []
    annotation_rows = []
    section = None
    for line in text.splitlines():
        if line == "//":
            break
        if line.startswith("  ") and section == "peaks":
            values = line.split()
            if len(values) != 3:
                raise ValueError(f"Invalid source peak row: {line!r}")
            peaks.append([Decimal(value) for value in values])
        elif line.startswith("  ") and section == "annotation":
            values = line.split()
            if len(values) != len(annotation_header):
                raise ValueError(f"Invalid source annotation row: {line!r}")
            annotation_rows.append([Decimal(values[0]), *values[1:]])
        elif line.startswith("PK$PEAK: "):
            fields["peak_header"] = line.removeprefix("PK$PEAK: ").split()
            section = "peaks"
        elif line.startswith("PK$ANNOTATION: "):
            annotation_header = line.removeprefix("PK$ANNOTATION: ").split()
            section = "annotation"
        elif ": " in line:
            tag, value = line.split(": ", 1)
            fields.setdefault(tag, []).append(value)
            section = None
        elif line:
            raise ValueError(f"Unrecognized source line: {line!r}")
    if "DEPRECATED" in fields:
        raise ValueError("Source record is deprecated in this snapshot")
    if len(fields.get("DATE", [])) != 1 or "peak_header" not in fields:
        raise ValueError("Source record must contain one DATE and a PK$PEAK section")
    classes = fields.get("CH$COMPOUND_CLASS", [])
    result = {
        "date": source_date(fields["DATE"][0]),
        "copyright": fields.get("COPYRIGHT", [""])[0],
        "compound_classes": [item for value in classes for item in value.split("; ")],
        "peak_header": fields["peak_header"],
        "peak_count": int(fields["PK$NUM_PEAK"][0]),
        "peaks": peaks,
    }
    if not all_fields:
        return result

    def single(tag, optional=False):
        values = fields.get(tag, [])
        if optional and not values:
            return ""
        if len(values) != 1:
            raise ValueError(f"Expected one {tag}, found {len(values)}")
        return values[0]

    def pairs(tag):
        result = []
        for value in fields.get(tag, []):
            parts = value.split(" ", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid {tag} subtag: {value!r}")
            result.append(parts)
        return result

    mass_spec = pairs("AC$MASS_SPECTROMETRY")

    def mass_spec_value(subtag):
        values = [value for key, value in mass_spec if key == subtag]
        if len(values) != 1:
            raise ValueError(f"Expected one AC$MASS_SPECTROMETRY: {subtag}")
        return values[0]

    authors = single("AUTHORS")
    lineage = single("SP$LINEAGE", optional=True)
    known_tags = {
        "ACCESSION", "RECORD_TITLE", "DATE", "AUTHORS", "LICENSE", "COPYRIGHT",
        "PUBLICATION", "PROJECT", "COMMENT", "CH$NAME", "CH$COMPOUND_CLASS",
        "CH$FORMULA", "CH$EXACT_MASS", "CH$SMILES", "CH$IUPAC", "CH$LINK",
        "SP$SCIENTIFIC_NAME", "SP$LINEAGE", "SP$LINK", "SP$SAMPLE",
        "AC$INSTRUMENT", "AC$INSTRUMENT_TYPE", "AC$MASS_SPECTROMETRY",
        "AC$CHROMATOGRAPHY", "AC$GENERAL", "AC$ION_MOBILITY",
        "MS$FOCUSED_ION", "MS$DATA_PROCESSING", "PK$SPLASH", "PK$NUM_PEAK", "peak_header",
    }
    result.update({
        "accession": single("ACCESSION"),
        "deprecated": {},
        "title": single("RECORD_TITLE"),
        "authors.text": authors,
        "authors.roles": re.findall(r"\[([a-z]{3})\]", authors),
        "license": single("LICENSE"),
        "publication": single("PUBLICATION", optional=True),
        "projects": fields.get("PROJECT", []),
        "comments": fields.get("COMMENT", []),
        "compound.names": fields.get("CH$NAME", []),
        "compound.formula": single("CH$FORMULA"),
        "compound.mass": Decimal(single("CH$EXACT_MASS")),
        "compound.smiles": single("CH$SMILES"),
        "compound.inchi": single("CH$IUPAC"),
        "compound.links": pairs("CH$LINK"),
        "species.name": single("SP$SCIENTIFIC_NAME", optional=True),
        "species.lineage": lineage.split("; ") if lineage else [],
        "species.links": pairs("SP$LINK"),
        "species.samples": fields.get("SP$SAMPLE", []),
        "acquisition.instrument": single("AC$INSTRUMENT"),
        "acquisition.instrument_type": single("AC$INSTRUMENT_TYPE"),
        "acquisition.ms_type": mass_spec_value("MS_TYPE"),
        "acquisition.ion_mode": mass_spec_value("ION_MODE"),
        "acquisition.mass_spectrometry": [pair for pair in mass_spec if pair[0] not in {"MS_TYPE", "ION_MODE"}],
        "acquisition.chromatography": pairs("AC$CHROMATOGRAPHY"),
        "acquisition.general": pairs("AC$GENERAL"),
        "acquisition.ion_mobility": pairs("AC$ION_MOBILITY"),
        "mass_spectrometry.focused_ion": pairs("MS$FOCUSED_ION"),
        "mass_spectrometry.data_processing": pairs("MS$DATA_PROCESSING"),
        "peak.splash": single("PK$SPLASH"),
        "annotation.header": annotation_header,
        "annotation.rows": annotation_rows,
        "unmapped_source_fields": {key: value for key, value in fields.items() if key not in known_tags},
    })
    return result


def api_fields(record, all_fields=False):
    peak = record["peak"]
    result = {
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
    if not all_fields:
        return result

    def pairs(values, key="subtag", value="value"):
        return [[item.get(key, "<missing>"), item.get(value, "<missing>")] for item in values]

    authors = record["authors"]
    compound = record["compound"]
    species = record.get("species", {})
    acquisition = record["acquisition"]
    mass_spec = acquisition["mass_spectrometry"]
    spectrum = record.get("mass_spectrometry", {})
    annotation = peak.get("annotation", {})
    header = annotation.get("header", [])
    columns = annotation.get("values", [])
    if len(columns) != len(header) or len({len(column) for column in columns}) > 1:
        rows = {"malformed_api_columns": columns}
    else:
        rows = [
            [Decimal(value) if name == "m/z" else value for name, value in zip(header, row)]
            for row in zip(*columns)
        ]
    result.update({
        "accession": record["accession"],
        "deprecated": record.get("deprecated", {}),
        "title": record["title"],
        "authors.text": ",".join(
            author["name"] + (" [" + author["marc-relator"] + "]" if author.get("marc-relator") else "")
            for author in authors
        ),
        "authors.roles": [author["marc-relator"] for author in authors if author.get("marc-relator")],
        "license": record["license"],
        "publication": record.get("publication", ""),
        "projects": [record["project"]] if record.get("project") else [],
        "comments": record.get("comments", []),
        "compound.names": compound["names"],
        "compound.formula": compound["formula"],
        "compound.mass": Decimal(str(compound["mass"])),
        "compound.smiles": compound["smiles"],
        "compound.inchi": compound["inchi"],
        "compound.links": pairs(compound.get("link", []), "database", "identifier"),
        "species.name": species.get("name", ""),
        "species.lineage": species.get("lineage", []),
        "species.links": pairs(species.get("link", []), "database", "identifier"),
        "species.samples": species.get("sample", []),
        "acquisition.instrument": acquisition["instrument"],
        "acquisition.instrument_type": acquisition["instrument_type"],
        "acquisition.ms_type": mass_spec["ms_type"],
        "acquisition.ion_mode": mass_spec["ion_mode"],
        "acquisition.mass_spectrometry": pairs(mass_spec.get("subtags", [])),
        "acquisition.chromatography": pairs(acquisition.get("chromatography", [])),
        "acquisition.general": pairs(acquisition.get("general", [])),
        "acquisition.ion_mobility": pairs(acquisition.get("ion_mobility", [])),
        "mass_spectrometry.focused_ion": pairs(spectrum.get("focused_ion", [])),
        "mass_spectrometry.data_processing": pairs(spectrum.get("data_processing", [])),
        "peak.splash": peak["splash"],
        "annotation.header": header,
        "annotation.rows": rows,
        "unmapped_source_fields": {},
    })
    return result


def order_only(left, right):
    if not isinstance(left, list) or not isinstance(right, list) or left == right:
        return False
    def key(value):
        return json.dumps(value, sort_keys=True, default=lambda number: str(number.normalize()))
    return Counter(map(key, left)) == Counter(map(key, right))


def subtag_text_equal(left, right):
    def valid(values):
        return isinstance(values, list) and all(
            isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair)
            for pair in values
        )
    return valid(left) and valid(right) and [" ".join(pair) for pair in left] == [" ".join(pair) for pair in right]


def load_accessions(sample_report=None, accessions_file=None, extra=()):
    values = json.loads(sample_report.read_text())["sample_accessions"] if sample_report else []
    if accessions_file:
        values.extend(line.strip() for line in accessions_file.read_text().splitlines() if line.strip())
    values.extend(extra)
    for accession in values:
        if not isinstance(accession, str) or not re.fullmatch(r"MSBNK-[A-Za-z0-9_]+-[A-Za-z0-9_]+", accession):
            raise ValueError(f"Invalid accession: {accession!r}")
    return list(dict.fromkeys(values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--source-reference", required=True, help="Snapshot commit/release for the report")
    parser.add_argument("--sample-report", type=Path, help="Historical report supplying sample_accessions")
    parser.add_argument("--accessions-file", type=Path, help="One accession per line; compare every listed record")
    parser.add_argument("--accession", action="append", default=[], help="Additional accession; may be repeated")
    parser.add_argument("--api", "--new", dest="api", default="https://msbi.ipb-halle.de/MassBank3-api")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all-fields", action="store_true", help="Compare all source-backed full-record field groups")
    parser.add_argument("--include-marc-roles", action="store_true", help="Also compare unfinished structured MARC roles")
    args = parser.parse_args()
    accessions = load_accessions(args.sample_report, args.accessions_file, args.accession)
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
        sources[accession] = primary_fields(content.decode("utf-8"), args.all_fields)
        if args.all_fields and not args.include_marc_roles:
            del sources[accession]["authors.roles"]
        source_hashes[accession] = hashlib.sha256(content).hexdigest()
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_reference": args.source_reference,
        "source_data": str(args.source_data),
        "sample_report": str(args.sample_report) if args.sample_report else None,
        "accessions_file": str(args.accessions_file) if args.accessions_file else None,
        "apis": {"new": args.api},
        "excluded_fields": [] if args.include_marc_roles else ["authors.roles"],
        "scope": "DATE, copyright, compound classes, peak header/count and all numeric peak values of each sampled full record",
        "methodology": "Missing historical dates are omitted; dates use ISO date-only format. Class lists follow '; ' source separators. Peak IDs are database identifiers, not source values. Peak order and decimal numeric equality are preserved, without rounding tolerance. Within differences, 'old' means source and 'new' means the API response. This is not a full-field or exhaustive-record audit.",
        "caveat": "The local snapshot may be newer than the deployed release; source mismatches require checking the deployed raw-text record before attributing them to conversion.",
        "cases": [],
    }
    if args.all_fields:
        report["scope"] = "All source-backed full-record field groups; active-record samples only, not every record or aggregate/search endpoint"
        report["methodology"] += (
            " AUTHORS text is reconstructed by comma-joining name entries with any structured MARC roles;"
            " structured roles are only checked with --include-marc-roles. COMMENT must be an array of complete strings;"
            " subtag/value objects are not accepted as equivalent."
            " Optional absent fields are compared with empty containers/text. Arrays preserve order and duplicates;"
            " order-only differences are reported separately, not silently normalized."
            " A subtag/value boundary difference with identical reconstructed source lines is marked text-preserving,"
            " rather than treated as data loss; legacy subtags can contain spaces."
            " Annotation columns are transposed to source rows; only their m/z column is numeric."
            " Unknown source tags are reported, not ignored. Peak IDs and derived neutral-loss output have no"
            " direct source field and are excluded; absent AC$GENERAL/AC$ION_MOBILITY data is not positive coverage."
        )
    clients = {
        side: Client(url, timeout=60, delay=0.1, max_bytes=16 * 1024 * 1024, parse_float=Decimal)
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
                    actual = api_fields(response.data, args.all_fields)
                    if args.all_fields and not args.include_marc_roles:
                        del actual["authors.roles"]
                    result["matching_fields"] = [key for key in expected if expected[key] == actual[key]]
                    result["differing_fields"] = [key for key in expected if expected[key] != actual[key]]
                    result["order_only_fields"] = [key for key in result["differing_fields"] if order_only(expected[key], actual[key])]
                    result["text_preserving_split_fields"] = [
                        key for key in result["differing_fields"]
                        if subtag_text_equal(expected[key], actual[key])
                    ]
                    changes = list(islice(differences(expected, actual), 101 if args.all_fields else 21))
                    limit = 100 if args.all_fields else 20
                    result["differences"] = changes[:limit]
                    result["differences_truncated"] = len(changes) > limit
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
                for field in next(iter(sources.values()))
            },
            "order_only_by_field": {
                field: sum(field in case[side].get("order_only_fields", []) for case in report["cases"])
                for field in next(iter(sources.values()))
            },
            "text_preserving_split_by_field": {
                field: sum(field in case[side].get("text_preserving_split_fields", []) for case in report["cases"])
                for field in next(iter(sources.values()))
            },
        }
        for side in clients
    }
    report["source_present_by_field"] = {
        field: sum(source[field] not in ("", [], {}, None) for source in sources.values())
        for field in next(iter(sources.values()))
    }
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report["summary"], indent=2))
    return int(any(summary["matching"] != summary["checked"] for summary in report["summary"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
