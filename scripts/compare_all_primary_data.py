#!/usr/bin/env python3
"""Audit every source/API accession; persist exact value differences and resumable progress."""

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
from urllib.parse import quote

from compare_apis import Client, inventory
from compare_primary_data import api_fields, order_only, primary_fields, subtag_text_equal


ACCESSION = re.compile(r"MSBNK-[A-Za-z0-9_]+-[A-Za-z0-9_]+")
DEFAULT_APIS = {
    "old": "https://msbi.ipb-halle.de/MassBank-api",
    "new": "https://msbi.ipb-halle.de/MassBank3-api",
}
PARSE_ERRORS = (ValueError, KeyError, TypeError, IndexError, AttributeError, InvalidOperation)


def encoded(value):
    # Decimal values are strings in diagnostic files, retaining every decimal place.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def value_differences(source, actual, path="$"):
    """Include missing values and array tails, without preview/count truncation."""
    if type(source) is type(actual) and source == actual:
        return
    if isinstance(source, dict) and isinstance(actual, dict):
        for key in sorted(source.keys() | actual.keys()):
            child = f"{path}[{json.dumps(key)}]"
            if key not in actual:
                yield {"path": child, "kind": "missing", "missing_from": "api", "source": source[key]}
            elif key not in source:
                yield {"path": child, "kind": "missing", "missing_from": "source", "api": actual[key]}
            else:
                yield from value_differences(source[key], actual[key], child)
    elif isinstance(source, list) and isinstance(actual, list):
        for index in range(max(len(source), len(actual))):
            child = f"{path}[{index}]"
            if index >= len(actual):
                yield {"path": child, "kind": "missing", "missing_from": "api", "source": source[index]}
            elif index >= len(source):
                yield {"path": child, "kind": "missing", "missing_from": "source", "api": actual[index]}
            else:
                yield from value_differences(source[index], actual[index], child)
    else:
        yield {"path": path, "kind": "value", "source": source, "api": actual,
               "source_type": type(source).__name__, "api_type": type(actual).__name__}


def source_index(directory):
    records = {}
    for path in sorted(directory.rglob("MSBNK-*.txt")):
        accession = path.stem
        if not ACCESSION.fullmatch(accession) or accession in records:
            raise ValueError(f"Invalid or duplicate source accession: {path}")
        content = path.read_bytes()
        lines = content.decode("utf-8").splitlines()
        if not lines or lines[0] != f"ACCESSION: {accession}":
            raise ValueError(f"Filename/ACCESSION disagreement: {path}")
        records[accession] = {
            "file": str(path.relative_to(directory)),
            "sha256": hashlib.sha256(content).hexdigest(),
            "deprecated": any(line.startswith("DEPRECATED: ") for line in lines),
        }
    if not records:
        raise ValueError(f"No source records in {directory}")
    return records


def source_values(text, include_roles):
    deprecated = [line.removeprefix("DEPRECATED: ") for line in text.splitlines()
                  if line.startswith("DEPRECATED: ")]
    if deprecated:
        if len(deprecated) != 1:
            raise ValueError("Multiple DEPRECATED lines")
        date, reason = deprecated[0].split(" ", 1)
        datetime.strptime(date, "%Y-%m-%d")
        return {"accession": text.splitlines()[0].removeprefix("ACCESSION: "),
                "deprecated": {"date": date, "reason": reason}}
    values = primary_fields(text, all_fields=True)
    if not include_roles:
        del values["authors.roles"]
    return values


def snapshot(client):
    response = client.get("/records/search")
    accessions = inventory(response)
    if any(not ACCESSION.fullmatch(value) for value in accessions):
        raise ValueError("API inventory contains invalid accessions")
    count = client.get("/records/count")
    if count.error or type(count.data) is not int:
        raise ValueError(f"Cannot read record count: {count.error or count.data!r}")
    duplicates = {key: value for key, value in Counter(accessions).items() if value > 1}
    return {"accessions": sorted(set(accessions)), "count": count.data,
            "inventory_rows": len(accessions), "duplicates": duplicates}


def compare_record(expected, response, deprecated=False):
    result = {"response": response.summary()}
    if response.error:
        result.update(outcome="error", error=response.error)
        return result
    if not isinstance(response.data, dict):
        result.update(outcome="error", error="Expected a record object, not a success-shaped error/scalar",
                      api_value=response.data)
        return result
    try:
        actual = (
            {key: response.data.get(key, "<missing>") for key in expected}
            if deprecated else api_fields(response.data, all_fields=True)
        )
    except PARSE_ERRORS as error:
        result.update(outcome="error", error=f"Invalid API record: {type(error).__name__}: {error}",
                      api_value=response.data)
        return result
    changed = {}
    for field, value in expected.items():
        changes = list(value_differences(value, actual[field]))
        if changes:
            classification = (
                "order_only" if order_only(value, actual[field]) else
                "text_preserving_split" if subtag_text_equal(value, actual[field]) else "value"
            )
            changed[field] = {"classification": classification, "differences": changes}
    result.update(outcome="different" if changed else "matching", fields=changed)
    return result


def write_summary(db, directory, config, before, after=None, fatal_error=None):
    stats = {name: {"outcomes": Counter(), "fields": {}, "examples": {},
                    "value_differences": 0} for name in config["apis"]}
    checked = 0
    with (directory / "differences.jsonl").open("w") as details:
        for accession, api, outcome, payload in db.execute(
                "SELECT accession,api,outcome,payload FROM results ORDER BY accession,api"):
            checked += 1
            result = json.loads(payload)
            stats[api]["outcomes"][outcome] += 1
            for field, change in result.get("fields", {}).items():
                counts = stats[api]["fields"].setdefault(field, Counter())
                counts[change["classification"]] += 1
                stats[api]["value_differences"] += len(change["differences"])
                examples = stats[api]["examples"].setdefault(field, [])
                if len(examples) < 5:
                    examples.append(accession)
            if outcome != "matching":
                details.write(payload + "\n")
    inventory_report = {}
    active = set(config["active_accessions"])
    deprecated = set(config["deprecated_accessions"])
    for api, start in before.items():
        present = set(start["accessions"])
        inventory_report[api] = {
            "count": start["count"], "inventory_rows": start["inventory_rows"],
            "duplicates": start["duplicates"], "missing_active": sorted(active - present),
            "not_in_source": sorted(present - active - deprecated),
            "deprecated_listed_as_active": sorted(present & deprecated),
            "count_matches_inventory": start["count"] == start["inventory_rows"],
            "stable": after[api] == start if after is not None else None,
        }
    complete = checked == config["total_accessions"] * len(config["apis"]) and after is not None
    summary = {
        "complete": complete and fatal_error is None, "fatal_error": fatal_error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_reference": config["source_reference"],
        "source_fingerprint": config["source_fingerprint"],
        "source_records": len(active) + len(deprecated), "active_records": len(active),
        "deprecated_records": len(deprecated), "total_accessions": config["total_accessions"],
        "completed_api_comparisons": checked, "apis": config["apis"],
        "excluded_fields": [] if config["include_marc_roles"] else ["authors.roles"],
        "results": stats, "inventory": inventory_report,
        "scope": "Full records, union of every source and API accession; no sampling. Deprecated records: accession and deprecation notice.",
        "methodology": "Numeric JSON values parsed as Decimal; diagnostic decimals serialized as strings. No rounding tolerance, text trimming, array sorting or difference truncation. Peak IDs and derived search values have no primary-data equivalent. Inventory stability does not guarantee unchanged content under the same accessions.",
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return summary


def run(args):
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    db_path = directory / "results.sqlite"
    if db_path.exists() != args.resume:
        raise ValueError("Use a new output directory, or --resume for an existing results.sqlite")
    sources = source_index(args.source_data)
    print(f"Indexed {len(sources)} source files", flush=True)
    api_urls = dict(args.api or DEFAULT_APIS.items())

    def client(url):
        return Client(url, args.timeout, args.delay, args.max_bytes,
                      parse_float=Decimal, keep_alive=True)

    before = {}
    for name, url in api_urls.items():
        connection = client(url)
        try:
            before[name] = snapshot(connection)
        finally:
            connection.close()
    accessions = sorted(set(sources).union(*(set(s["accessions"]) for s in before.values())))
    config = {
        "format_version": 1, "source_data": str(args.source_data.resolve()),
        "source_reference": args.source_reference, "source_fingerprint": fingerprint(sources),
        "apis": api_urls, "include_marc_roles": args.include_marc_roles,
        "active_accessions": [key for key, value in sources.items() if not value["deprecated"]],
        "deprecated_accessions": [key for key, value in sources.items() if value["deprecated"]],
        "total_accessions": len(accessions), "initial_inventory_fingerprint": fingerprint(before),
    }
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS metadata (config TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS results (accession TEXT, api TEXT, outcome TEXT NOT NULL,"
               "payload TEXT NOT NULL, PRIMARY KEY(accession,api))")
    if args.resume:
        saved = db.execute("SELECT config FROM metadata").fetchone()
        if saved is None or json.loads(saved[0]) != config:
            db.close()
            raise ValueError("Resume rejected: source files, APIs, inventories or comparison settings changed")
    else:
        db.execute("INSERT INTO metadata VALUES (?)", (encoded(config),))
        db.commit()
    completed = {row[0] for row in db.execute(
        "SELECT accession FROM results GROUP BY accession HAVING count(*)=?", (len(api_urls),))}
    pending = iter(value for value in accessions if value not in completed)
    local = threading.local()
    connections = []
    lock = threading.Lock()

    def check(accession):
        if not hasattr(local, "clients"):
            local.clients = {name: client(url) for name, url in api_urls.items()}
            with lock:
                connections.extend(local.clients.values())
        source = sources.get(accession)
        expected, source_error = None, None
        if source is not None:
            try:
                content = (args.source_data / source["file"]).read_bytes()
                if hashlib.sha256(content).hexdigest() != source["sha256"]:
                    raise ValueError("Source file changed during the audit")
                expected = source_values(content.decode("utf-8"), args.include_marc_roles)
            except (*PARSE_ERRORS, OSError) as error:
                source_error = f"{type(error).__name__}: {error}"
        rows = []
        for name, connection in local.clients.items():
            response = connection.get("/records/" + quote(accession, safe=""))
            if source is None or source_error:
                result = {"outcome": "source_error" if source_error else "missing_source",
                          "error": source_error or "API accession has no original file",
                          "response": response.summary()}
            else:
                result = compare_record(expected, response, source["deprecated"])
            result.update(accession=accession, api=name, source=source)
            rows.append((accession, name, result["outcome"], encoded(result)))
        return rows

    after, fatal = None, None
    try:
        print(f"Comparing all {len(accessions)} accessions against {len(api_urls)} API(s); "
              f"{len(completed)} already complete", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}

            def submit():
                accession = next(pending, None)
                if accession is not None:
                    futures[executor.submit(check, accession)] = accession

            for _ in range(args.workers):
                submit()
            while futures:
                ready, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in ready:
                    accession = futures.pop(future)
                    db.executemany("INSERT INTO results VALUES (?,?,?,?)", future.result())
                    db.commit()
                    completed.add(accession)
                    if len(completed) % 1000 == 0:
                        print(f"{len(completed)}/{len(accessions)} accessions committed", flush=True)
                    submit()
        after = {}
        for name, url in api_urls.items():
            connection = client(url)
            try:
                after[name] = snapshot(connection)
            finally:
                connection.close()
    except (KeyboardInterrupt, *PARSE_ERRORS, OSError) as error:
        fatal = f"{type(error).__name__}: {error}"
        print(fatal, file=sys.stderr)
        after = None
    finally:
        for connection in connections:
            connection.close()
        summary = write_summary(db, directory, config, before, after, fatal)
        db.close()
    print(encoded({name: value["outcomes"] for name, value in summary["results"].items()}), flush=True)
    if not summary["complete"]:
        return 2
    inventory_ok = all(
        value["stable"] and value["count_matches_inventory"] and not any(
            value[key] for key in ("duplicates", "missing_active", "not_in_source", "deprecated_listed_as_active")
        ) for value in summary["inventory"].values()
    )
    return int(not inventory_ok or any(
        outcome != "matching" and count
        for result in summary["results"].values() for outcome, count in result["outcomes"].items()
    ))


def api_option(value):
    name, separator, url = value.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise argparse.ArgumentTypeError("Use --api NAME=https://host/base-path")
    return name, url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--api", type=api_option, action="append", help="Repeatable; defaults to old and new public APIs")
    parser.add_argument("--output", type=Path, required=True, help="Directory for SQLite progress, summary and JSONL differences")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--include-marc-roles", action="store_true", help="Default excludes unfinished structured MARC roles")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent accessions; each worker queries APIs sequentially")
    parser.add_argument("--delay", type=float, default=0.05, help="Pause before each request, per worker")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()
    if args.workers < 1 or args.delay < 0 or args.timeout <= 0 or args.max_bytes < 1:
        parser.error("workers/max-bytes must be positive; timeout > 0 and delay >= 0")
    if args.api and len(dict(args.api)) != len(args.api):
        parser.error("API names must be unique")
    try:
        return run(args)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"Audit failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
