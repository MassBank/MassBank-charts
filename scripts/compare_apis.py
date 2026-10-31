#!/usr/bin/env python3
"""Compare MassBank API JSON and sequential, warmed HTTP response latency."""

import argparse
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import http.client
from itertools import islice
import json
import math
from pathlib import Path
import random
import statistics
import time
from urllib.parse import quote, urlencode, urlsplit


IGNORED_PATHS = {
    "/metadata": {("version",), ("timestamp",), ("git_commit",)},
    "/status": {
        ("api", "version"), ("postgres", "version"),
        ("export_service", "version"), ("similarity_service", "version"),
    },
}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def normalize(value, endpoint, path=()):
    """Only ignore documented deployment fields and unordered result collections."""
    route = endpoint.split("?", 1)[0]
    if isinstance(value, dict):
        return {
            key: normalize(item, endpoint, path + (key,))
            for key, item in value.items()
            if path + (key,) not in IGNORED_PATHS.get(route, set())
        }
    if isinstance(value, list):
        items = [normalize(item, endpoint, path + ("[]",)) for item in value]
        unordered = (
            (route == "/records/search" and path in {("data",), ("data", "[]", "peakPairs")})
            or (route == "/records" and path == ())
            or (route in {"/filter/browse", "/metadata"} and len(path) == 1)
        )
        return sorted(items, key=encoded) if unordered else items
    return value


def differences(old, new, path="$"):
    if old == new and type(old) is type(new):
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            child = f"{path}.{key}"
            if key not in old or key not in new:
                yield {"path": child, "kind": "missing", "missing_from": "old" if key not in old else "new"}
            else:
                yield from differences(old[key], new[key], child)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            yield {"path": path, "kind": "length", "old": len(old), "new": len(new)}
        for index, (left, right) in enumerate(zip(old, new)):
            yield from differences(left, right, f"{path}[{index}]")
    else:
        def preview(value):
            if isinstance(value, (dict, list)):
                return {"type": type(value).__name__, "length": len(value), "preview": encoded(value)[:500]}
            if isinstance(value, str) and len(value) > 500:
                return value[:500] + "... [truncated]"
            return value
        yield {"path": path, "kind": "value", "old": preview(old), "new": preview(new)}


@dataclass
class Response:
    status: int | None
    milliseconds: float
    size: int
    sha256: str | None
    data: object = None
    error: str | None = None

    def summary(self):
        return {
            "status": self.status, "milliseconds": self.milliseconds,
            "bytes": self.size, "body_sha256": self.sha256, "error": self.error,
        }


class Client:
    def __init__(self, base, timeout, delay, max_bytes):
        self.url = urlsplit(base.rstrip("/"))
        if self.url.scheme not in {"http", "https"} or not self.url.hostname:
            raise ValueError(f"Invalid API URL: {base}")
        if self.url.username or self.url.password or self.url.query or self.url.fragment:
            raise ValueError("API base URLs must not contain credentials, query strings or fragments")
        connection = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
        self.connection = connection(self.url.hostname, self.url.port, timeout=timeout)
        self.delay = delay
        self.max_bytes = max_bytes

    def get(self, endpoint):
        time.sleep(self.delay)
        # Fresh connections avoid asymmetric ingress idle timeouts between pairs.
        self.connection.close()
        start = time.perf_counter_ns()
        status = None
        body = b""
        try:
            self.connection.request(
                "GET", self.url.path + endpoint,
                headers={"Accept": "application/json", "Accept-Encoding": "identity", "Connection": "close",
                         "User-Agent": "MassBank-API-comparison/1.0"},
            )
            response = self.connection.getresponse()
            status = response.status
            body = response.read(self.max_bytes + 1)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            if len(body) > self.max_bytes:
                self.connection.close()
                return Response(status, elapsed, len(body), None, error="Response exceeds configured byte limit")
        except (OSError, http.client.HTTPException) as error:
            self.connection.close()
            return Response(status, (time.perf_counter_ns() - start) / 1e6,
                            len(body), None, error=f"{type(error).__name__}: {error}")
        sha = hashlib.sha256(body).hexdigest()
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            return Response(status, elapsed, len(body), sha, error=f"Invalid JSON: {error}")
        error = None if status == 200 else f"HTTP {status}"
        return Response(status, elapsed, len(body), sha, data, error)

    def close(self):
        self.connection.close()


def comparison(old, new, endpoint):
    if old.error or new.error:
        return {"json_equal": False, "semantic_equal": False, "differences": [],
                "error": {"old": old.error, "new": new.error}}
    left, right = normalize(old.data, endpoint), normalize(new.data, endpoint)
    changes = list(islice(differences(left, right), 21))
    result = {
        "json_equal": encoded(old.data) == encoded(new.data),
        "semantic_equal": encoded(left) == encoded(right),
        "old_semantic_sha256": digest(left), "new_semantic_sha256": digest(right),
        "differences": changes[:20], "differences_truncated": len(changes) > 20,
    }
    if endpoint.split("?", 1)[0] == "/records/search":
        rows = [value.get("data", []) for value in [old.data, new.data] if isinstance(value, dict)]
        if len(rows) != 2 or any(
            not isinstance(items, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("accession"), str) for item in items
            ) for items in rows
        ):
            result["search_inventory"] = {"error": "Invalid search hit shape"}
        else:
            old_map, new_map = [{item["accession"]: item for item in items} for items in rows]
            result["search_inventory"] = {
                "old_hits": len(rows[0]), "new_hits": len(rows[1]),
                "old_duplicate_accessions": len(rows[0]) - len(old_map),
                "new_duplicate_accessions": len(rows[1]) - len(new_map),
                "only_old": sorted(old_map.keys() - new_map.keys()),
                "only_new": sorted(new_map.keys() - old_map.keys()),
            }
    return result


def distribution(responses):
    values = sorted(r.milliseconds for r in responses if not r.error)
    return {
        "successful": len(values), "failed": len(responses) - len(values),
        "median_ms": statistics.median(values) if values else None,
        "p95_ms": values[math.ceil(0.95 * len(values)) - 1] if values else None,
        "min_ms": min(values) if values else None,
        "max_ms": max(values) if values else None,
        "samples": [r.summary() for r in responses],
    }


def sample_accessions(accessions, count, seed):
    """Deterministic round-robin sampling across contributor prefixes."""
    rng = random.Random(seed)
    groups = defaultdict(list)
    for accession in sorted(set(accessions)):
        groups[accession.split("-")[1] if "-" in accession else accession].append(accession)
    keys = sorted(groups)
    rng.shuffle(keys)
    for group in groups.values():
        rng.shuffle(group)
    result = []
    target = min(count, len(set(accessions)))
    while len(result) < target:
        for key in keys:
            if groups[key] and len(result) < count:
                result.append(groups[key].pop())
    return result


def inventory(response):
    if response.error or not isinstance(response.data, dict) or not isinstance(response.data.get("data"), list):
        raise ValueError(f"Cannot read complete accession inventory: {response.error or 'invalid response shape'}")
    rows = response.data["data"]
    if not rows or any(not isinstance(row, dict) or not isinstance(row.get("accession"), str) for row in rows):
        raise ValueError("Accession inventory is empty or contains invalid rows")
    return sorted(row["accession"] for row in rows)


def search_case(name, **query):
    return name, "/records/search?" + urlencode(query), True


def build_cases(accessions, representative):
    cases = [
        ("status", "/status", True), ("count", "/records/count", True),
        ("metadata", "/metadata", True), ("browse", "/filter/browse", True),
        ("all-accessions", "/records/search", True),
    ]
    for index, accession in enumerate(accessions):
        path = "/records/" + quote(accession, safe="")
        cases.extend([(f"record:{accession}", path, index < 3),
                      (f"simple:{accession}", path + "/simple", index < 3)])
    compound = representative["compound"]
    if not isinstance(compound, dict) or not compound.get("formula") or not compound.get("names"):
        raise ValueError("Representative record must have a compound formula and name for bounded queries")
    cases.extend([
        search_case("formula", formula=compound["formula"]),
        search_case("name", compound_name=compound["names"][0]),
        search_case("exact-mass", exact_mass=compound["mass"], mass_tolerance=0.01),
        search_case("contributor", contributor=representative["accession"].split("-")[1]),
        search_case("ion-mode", ion_mode="POSITIVE"),
        search_case("ms-type", ms_type="MS2"),
        ("records-by-formula", "/records?" + urlencode({"formula": compound["formula"]}), True),
    ])
    if compound.get("smiles") not in {None, "", "N/A"}:
        cases.append(search_case("bingo-substructure", substructure=compound["smiles"]))
    peaks = representative.get("peak", {}).get("peak", {}).get("values", [])
    if peaks:
        mz = peaks[0]["mz"]
        cases.append(search_case("peak", peaks=mz, intensity=1))
        precursor = next((item["value"] for item in representative["mass_spectrometry"].get("focused_ion", [])
                          if item["subtag"] == "PRECURSOR_M/Z"), None)
        if precursor is not None:
            cases.append(search_case("neutral-loss", neutral_loss=abs(float(precursor) - mz), intensity=1))
    return cases


def run(args, report):
    clients = {
        "old": Client(args.old, args.timeout, args.delay, args.max_response_mib * 1024**2),
        "new": Client(args.new, args.timeout, args.delay, args.max_response_mib * 1024**2),
    }
    pair_number = 0

    def pair(endpoint):
        nonlocal pair_number
        order = ["old", "new"] if pair_number % 2 == 0 else ["new", "old"]
        pair_number += 1
        return {side: clients[side].get(endpoint) for side in order}

    try:
        initial = pair("/records/search")
        report["preflight"] = {"inventory": {side: response.summary() for side, response in initial.items()}}
        ids = {side: inventory(response) for side, response in initial.items()}
        del initial
        counts = pair("/records/count")
        metadata = pair("/metadata")
        report["preflight"].update({
            "counts": {side: response.summary() for side, response in counts.items()},
            "metadata": {side: response.summary() for side, response in metadata.items()},
        })
        for responses in [counts, metadata]:
            if any(response.error for response in responses.values()):
                raise ValueError(f"Preflight failed: { {s: r.summary() for s, r in responses.items()} }")
        if any(type(r.data) is not int or r.data < 0 for r in counts.values()):
            raise ValueError("Record counts must be nonnegative JSON integers")
        if any(not isinstance(r.data, dict) for r in metadata.values()):
            raise ValueError("Metadata must be a JSON object")
        dataset = report["dataset"] = {
            "accessions_equal": ids["old"] == ids["new"],
            "only_old": sorted(set(ids["old"]) - set(ids["new"])),
            "only_new": sorted(set(ids["new"]) - set(ids["old"])),
            "old": {}, "new": {},
        }
        for side in clients:
            dataset[side] = {
                "count": counts[side].data, "inventory_count": len(ids[side]),
                "duplicate_accessions": len(ids[side]) - len(set(ids[side])),
                "accessions_sha256": digest(ids[side]),
                "metadata": {key: metadata[side].data.get(key)
                             for key in ["version", "timestamp", "git_commit", "spectra_count", "compound_count"]},
            }
        dataset["expected_release_matches_new"] = (
            not args.expected_release or metadata["new"].data.get("version") == args.expected_release
        )
        if not dataset["expected_release_matches_new"]:
            raise ValueError(f"New API does not report expected data release {args.expected_release}")
        common = set(ids["old"]) & set(ids["new"])
        if not common:
            raise ValueError("APIs have no accessions in common")
        sampled = sample_accessions(common, len(common) if args.all_records else args.samples, args.seed)
        anchor = "MSBNK-IPB_Halle-PB011601"
        if anchor in common:
            sampled = [anchor] + [item for item in sampled if item != anchor]
            if not args.all_records:
                sampled = sampled[:args.samples]
        report["sample_accessions"] = sampled
        representative = clients["old"].get("/records/" + quote(sampled[0], safe=""))
        if representative.error:
            raise ValueError(f"Cannot fetch representative record: {representative.error}")
        cases = build_cases(sampled, representative.data)
        report["cases"] = []
        print(f"Inventory: old={len(ids['old'])}, new={len(ids['new'])}, identical={dataset['accessions_equal']}", flush=True)
        print("Case | JSON / semantic equal | old median ms | new median ms | new/old", flush=True)
        for name, endpoint, benchmark in cases:
            first = pair(endpoint)
            if endpoint == "/status":
                report["service_status"] = {side: response.data for side, response in first.items()}
            first_hashes = {side: digest(normalize(response.data, endpoint))
                            for side, response in first.items() if not response.error}
            item = {"name": name, "endpoint": endpoint, "benchmark": benchmark,
                    "responses": {side: response.summary() for side, response in first.items()},
                    "comparison": comparison(first["old"], first["new"], endpoint)}
            report["cases"].append(item)
            samples = {"old": [], "new": []}
            item["warmup_errors"] = []
            item["response_changed_during_measurement"] = []
            if benchmark:
                for iteration in range(args.warmup + args.repeats):
                    observed = pair(endpoint)
                    for side, response in observed.items():
                        if iteration < args.warmup:
                            if response.error:
                                item["warmup_errors"].append({"side": side, **response.summary()})
                        else:
                            samples[side].append(replace(response, data=None))
                        if not response.error and not first[side].error:
                            if digest(normalize(response.data, endpoint)) != first_hashes[side]:
                                item["response_changed_during_measurement"].append({"side": side, "iteration": iteration})
                item["performance"] = {side: distribution(values) for side, values in samples.items()}
                old_ms, new_ms = [item["performance"][side]["median_ms"] for side in ["old", "new"]]
                ratio = new_ms / old_ms if old_ms and new_ms is not None else None
                item["new_over_old_median_ratio"] = ratio
                timing = f"{old_ms:.2f} | {new_ms:.2f} | {ratio:.2f}x" if ratio is not None else "unavailable"
            else:
                timing = "not benchmarked"
            match = item["comparison"]
            print(f"{name} | {match['json_equal']} / {match['semantic_equal']} | {timing}", flush=True)
        final = pair("/records/search")
        final_counts = pair("/records/count")
        dataset["stable_during_run"] = all(
            inventory(final[side]) == ids[side] and not final_counts[side].error
            and final_counts[side].data == counts[side].data for side in clients
        )
        dataset_ok = dataset["accessions_equal"] and dataset["stable_during_run"] and all(
            dataset[side]["count"] == dataset[side]["inventory_count"]
            and dataset[side]["duplicate_accessions"] == 0 for side in clients
        )
        mismatches = [item["name"] for item in report["cases"] if not item["comparison"]["semantic_equal"]]
        unstable = [item["name"] for item in report["cases"] if item["response_changed_during_measurement"]]
        failed = [item["name"] for item in report["cases"]
                  if item["warmup_errors"] or any(
                      stats["failed"] for stats in item.get("performance", {}).values())]
        report["summary"] = {
            "dataset_checks_passed": dataset_ok, "semantic_mismatches": mismatches,
            "json_mismatches": [item["name"] for item in report["cases"] if not item["comparison"]["json_equal"]],
            "unstable_cases": unstable, "benchmark_failures": failed,
            "sampled_records": len(sampled), "all_common_records_compared": len(sampled) == len(common),
            "passed": dataset_ok and not mismatches and not unstable and not failed,
        }
        return 0 if report["summary"]["passed"] else 1
    finally:
        for client in clients.values():
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", default="https://msbi.ipb-halle.de/MassBank-api")
    parser.add_argument("--new", default="https://msbi.ipb-halle.de/MassBank3-api")
    parser.add_argument("--expected-release")
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--all-records", action="store_true", help="Compare every common full/simple record; many requests")
    parser.add_argument("--seed", type=int, default=202603)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.1, help="Pause before every request, seconds")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--max-response-mib", type=int, default=64)
    parser.add_argument("--output", type=Path, default=Path("api-comparison.json"))
    args = parser.parse_args()
    if min(args.samples, args.repeats, args.max_response_mib) < 1 or args.warmup < 0:
        parser.error("samples, repeats and max-response-mib must be positive; warmup must be nonnegative")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not math.isfinite(args.delay) or args.delay < 0:
        parser.error("timeout must be positive and delay nonnegative, both finite")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "methodology": {
            "concurrency": 1, "order": "alternating old/new for each pair",
            "timing": "HTTP request through complete response body; excludes JSON decoding and pause",
            "connection": "fresh connection per request with verified TLS; TCP/TLS setup included",
            "compression": "identity", "percentile": "nearest-rank p95 of successful measured requests",
            "scope": "end-to-end public deployment latency, not isolated database or throughput benchmark",
            "normalization": "unordered search hits/peakPairs, record lists and top-level metadata/browse lists only",
            "ignored_fields": {route: [".".join(path) for path in sorted(paths)]
                               for route, paths in IGNORED_PATHS.items()},
            "record_arrays": "preserved; null, missing fields, strings and numeric values are not normalized",
        },
    }
    try:
        code = run(args, report)
    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException) as error:
        report["fatal_error"] = f"{type(error).__name__}: {error}"
        print(report["fatal_error"], flush=True)
        code = 2
    except KeyboardInterrupt:
        report["fatal_error"] = "Interrupted; partial report only"
        code = 130
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Report: {args.output}; exit status {code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
