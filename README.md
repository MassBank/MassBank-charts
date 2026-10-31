# MassBank-charts
This repo contains the helm charts to deploy a full MassBank software system into a Kubernetes instance. 

## Installing MassBank from helm repo

The charts are available from our helm repo. You can add them to your helm with:
```
helm repo add massbank https://massbank.github.io/MassBank-charts
```
and update them later with:
```
helm repo update
```

The whole installation is triggered by installing the umbrella chart `massbank`.
To install, we recommend keeping (local) values files with the helm variables and real passwords:
```
helm install massbank massbank/massbank -f msbi-values.yaml -n massbank
```
and later updates can be performed via 
```
helm upgrade massbank massbank/massbank --version v2025.06.2 -f msbi-values.yaml -n massbank
```
Some example values files can be found in the root of this repo.

## Shared JPA database

The umbrella chart uses one PostgreSQL database for the API and export API.
Only the export API's `/app-import.jar` creates the JPA tables and imports the
records. The legacy `massbank-dbtool` is no longer an umbrella dependency.
PostgreSQL initialization installs Bingo in the shared database; the importer
adds read views, search indexes and derived neutral-loss/name/metadata projections
in the same database. Only the importer refreshes these before enabling readiness.
The frontend's internal and
public API URLs target these two services, not the old databases.

The example values use one `massbankDatabase` YAML anchor for
`postgres.auth.database`, `massbank-api.massbankApiDatabase`, and
`massbank-export-api.massbankExportApiDatabase`. All three must match; inconsistent
overrides fail chart rendering. When using `--set`, override all three resolved
values rather than only the top-level anchor.

This branch pins the tested `test-shared-jpa-<commit>` Quay images; it is not a
production release. The changed subcharts use local `file://` dependencies so
their source and packaged versions can be tested before publishing releases:

```sh
helm dependency build ./charts/massbank
helm lint ./charts/massbank-api ./charts/massbank-export-api ./charts/massbank-frontend ./charts/massbank
helm unittest ./charts/massbank-api ./charts/massbank-export-api ./charts/massbank
helm template massbank-dev ./charts/massbank -n massbank-dev -f msbi-values-dev.yaml
```

### Upgrading the development deployment

`msbi-values-dev.yaml` configures the complete system at
**https://msbi.ipb-halle.de/MassBank3/**, using `massbank_shared` and the full
official **2026.03** release on `massbank-dev-massbank-data-pvc`, also used by the
old installation at `/MassBank/`. The matching frontend image retains the
previously deployed CSP behavior and displays source dates without invented
historical dates. The older `massbank` and `records` databases are not removed.
The current development values disable the importer for software-only upgrades
of this already populated database. Set `massbank-export-api.dataImport.enabled=true`
explicitly for a fresh installation or a deliberate new dataset import.

Existing shared databases need the matching export API branch's
`src/main/resources/shared-api.sql` migration before these optimized images are
started. With no import running, apply that file transactionally using
`psql -v ON_ERROR_STOP=1 --single-transaction`. It builds initial derived search
data from the existing JPA records; no record reimport is necessary. Then
vacuum/analyze the record and peak tables and analyze the three materialized
views. The export API README documents this migration and its regression test.
This migration has already been applied to the development deployment.

PostgreSQL init scripts run only for an empty data volume. For an existing PVC,
first create `massbank_shared` owned by `massbank`, run the installed
`/opt/bingo-postgres/init-scripts/000_bingo_install.sql` in that database, and set
`bingo.bingo_config.ALLOW_NON_UNIQUE_DEAROMATIZATION` to `1`. Use administrator
access for this provisioning; keep credentials in the existing `postgres-pw`
Secret. No record tables or records are created by this provisioning step.

When changing `postgres.auth.database` on an existing release, first roll the
PostgreSQL StatefulSet to the matching `POSTGRES_DB` environment value and wait
for it to be ready. This prevents its restart from interrupting the new import.
Then run:

```sh
helm upgrade massbank-dev ./charts/massbank -n massbank-dev \
  -f msbi-values-dev.yaml --reset-values --wait --wait-for-jobs --timeout 2h
```

The export API waits for the import completion marker before starting. The Go
API's readiness probe checks the database, not just its version endpoint. Both
API Deployments restart when their connection ConfigMaps change.
The importer bulk-builds the Bingo index after loading all JPA records; readiness
remains false until the index and database statistics are complete.

Imports **replace** the configured dataset and require a maintenance window.
Jobs use a chart-versioned name, no automatic retry, and no default TTL: retaining
the completed Job prevents an ordinary same-version upgrade from repeating the
import. A new export chart version creates a new import Job. Set
`massbank-export-api.dataImport.enabled=false` for upgrades that must not import
data, or deliberately delete only the named import Job to rerun it. Disabling
the importer never re-enables dbtool.

To change the dataset without changing chart versions, update both
`massbank-data.version` and `massbank-export-api.dataImport.dataVersion`.
Update `massbank-similarity-api.podAnnotations.massbank.org/data-version` too,
so the in-memory similarity dataset reloads. During a maintenance window, delete
only the completed download and import Jobs for this release before the Helm
upgrade. The recreated importer and similarity pods wait for the new download.
For the currently pinned chart versions:

```sh
kubectl -n massbank-dev delete \
  job/massbank-dev-massbank-data-download-2026-10-28 \
  job/massbank-dev-massbank-export-api-import-2-6-2 --ignore-not-found
helm upgrade massbank-dev ./charts/massbank -n massbank-dev \
  -f msbi-values-dev.yaml --set massbank-export-api.dataImport.enabled=true \
  --reset-values --wait --wait-for-jobs --timeout 2h
```

### Comparing the old and shared-database APIs

The standard-library-only comparison script checks complete accession inventories
and counts, then deterministically samples records across contributor prefixes.
It compares full/simple records, metadata, browse filters, formula/name/mass
searches, Bingo substructure, peak and neutral-loss searches, and a filtered record
list. Defaults target `/MassBank-api` (old) and `/MassBank3-api` (new).
Python 3.10 or later is required.

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/compare_apis.py --expected-release 2026.03 \
  --samples 100 --warmup 2 --repeats 10 --delay 0.1 \
  --output comparison-results/2026-10-31-release-2026.03.json
```

The JSON report retains response hashes, status codes, differences, raw timing
samples, median and nearest-rank p95. JSON equality and semantic equality are
reported separately. Semantic comparison sorts unordered search results,
`peakPairs`, record lists and metadata/browse lists, and excludes only deployment
versions, import timestamps and commit metadata (the report lists exact paths).
Record arrays, missing fields, nulls and values are not normalized. Differences
are bounded to 20 examples per case; complete normalized-response hashes are
also recorded. `--all-records` checks every common full/simple record instead of
sampling, generating many requests; only three sampled full/simple records and
the non-record cases receive repeated performance measurements.

Requests are sequential, with alternating old/new order, a fresh TLS connection
per request, no compression, warmups excluded, and a pause before every request.
Fresh connections avoid asymmetric ingress keep-alive expiry between pairs.
Timing includes TCP/TLS setup and the complete HTTP body, but excludes JSON processing. Errors are
retained, not retried or counted as fast successful responses. Inventories/counts
are checked again after measurement to detect dataset changes. Exit status is
`0` for matching stable results, `1` for differences/errors, and `2` for a failed
preflight or incomplete run. The old API's metadata version may be stale even
when its accession inventory matches; the script exposes both.

This measures public end-to-end deployment latency, not isolated database speed
or throughput. CPU limits, PostgreSQL versions, caches, ingress and concurrent
traffic differ; small-sample p95 values are descriptive, not confidence bounds.

### Comparison results, 2026-10-31

[Release provenance](comparison-results/data-release-provenance.json) confirms
that the old API contains all **139,006** active accessions of **2026.03**, with
no extras or omissions. Release 2025.10 has only 134,440 active records.
Five changed-record probes also confirm ChemOnt links added after 2025.10.
The old `/metadata.version` is stale; it does not identify the installed dataset.
The development instance was reimported from 2026.03: 139,006 active records,
234 deprecated records, zero failed imports. The old installation was not changed.

[Full comparison and timing samples](comparison-results/2026-10-31-release-2026.03.json)
cover 100 contributor-stratified records (full and simple), 215 cases total,
and 21 repeatedly measured cases with two warmups and ten measured requests per
API. Inventories remained identical and stable; there were no HTTP/transport
failures or unstable measured responses. The initial keep-alive client encountered
an expired connection during preflight; the recorded complete run uses fresh TLS
connections and no retries.

| Case | Old median / p95 (ms) | Shared JPA median / p95 (ms) | New / old median |
|---|---:|---:|---:|
| Record count | 122.12 / 143.19 | 129.68 / 136.64 | 1.06 |
| All accessions | 2422.45 / 2940.84 | 4599.36 / 4767.02 | 1.90 |
| Metadata | 328.86 / 364.29 | 1055.39 / 1510.76 | 3.21 |
| Full record PB011601 | 133.38 / 137.79 | 118.05 / 127.83 | 0.89 |
| Formula search | 86.36 / 100.24 | 204.80 / 229.09 | 2.37 |
| Bingo substructure | 106.83 / 121.97 | 93.43 / 97.68 | 0.87 |
| Peak search | 964.05 / 1068.45 | 1909.82 / 2109.73 | 1.98 |
| Neutral-loss search | 228.25 / 270.64 | 13330.33 / 13706.05 | 58.40 |

This is **not full output compatibility**: 204/215 cases differ under the
documented normalization (all 200 full/simple record responses, metadata,
the filtered record list, peak search and neutral-loss search). Observations:

- Peak IDs differ between imports, and legacy float rounding differs from JPA
  numeric values; peak-pair identifiers therefore differ too.
- Date formatting differs; PB011601 additionally has `date.modified` equal to
  year 0001 in the new API instead of the legacy fallback date 2019-06-20.
- Compound class splitting differs, including metadata histograms
  (1,886 versus 1,794 class entries). Optional fields and peak headers also differ.
- Peak search `107.04000091552734`, intensity 1, returns 23,163 old versus 23,164
  new hits. The extra accession is `MSBNK-PFOS_research_group-FFF00074`:
  the old peak is `106.73999786376953`, the new peak `106.740001`, on opposite
  sides of the default 0.3 tolerance boundary.
- Neutral-loss search has the same 2,378 accessions but different peak IDs and
  a pronounced latency regression. The script returns exit status 1 for these
  differences; it does not hide them or change the applications to match.

The old API has a 1 CPU / 400 MiB limit, the new API 2 CPU / 1 GiB.
PostgreSQL versions are 17.9 and 17.11 respectively, with no explicit container
resource limits. These are measurements of the actual deployments, not a
hardware-controlled database benchmark. Record samples are not exhaustive.

### Performance optimization and repeat measurements

The [unchanged repeat](comparison-results/2026-10-31-repeat-before-optimization.json)
confirmed the regressions, including 13,134 ms for neutral loss versus 235 ms
on the old API. [Query plans before](comparison-results/performance-plans-before.txt)
identified repeated precursor JSON/regex parsing across almost three million
peaks, per-result formula parsing, full formula scans and repeated metadata
aggregation.

The deployed correction uses covering expression indexes for atom counts,
browse/formula/peak lookups, and importer-maintained neutral-loss, name-search
and metadata projections. The final covering indexes also eliminate heap reads
for neutral-loss hits and browse facets. The Go API reads the prepared metadata
aggregates; the legacy mode is unchanged. The importer refreshes all projections
before marking the database ready, and refresh failures keep readiness false.
Canonical records, peak IDs, release and import timestamp were not changed.

[Final measurements](comparison-results/2026-10-31-after-covering-indexes.json),
again two warmups and ten measured requests per API:

| Case | Shared before (median ms) | Shared after (median / p95 ms) | Old API, final run (median ms) |
|---|---:|---:|---:|
| Neutral loss | 13134.27 | 226.81 / 276.50 | 235.75 |
| All accessions | 4888.86 | 1114.05 / 1281.62 | 2396.43 |
| Metadata | 1093.20 | 168.09 / 180.96 | 327.31 |
| Browse filters | 642.68 | 376.78 / 442.80 | 444.79 |
| Formula search | 192.47 | 88.14 / 91.52 | 86.35 |
| Name search | 990.31 | 467.27 / 501.18 | 528.97 |
| Peak search | 2005.74 | 422.23 / 451.47 | 940.28 |

Neutral loss is about 58 times faster than the repeated pre-fix measurement and
now comparable to the old API. The large regressions are removed; this does not
mean every route is faster (the three simple-record examples still take roughly
5-8% longer than the old API). Resource limits and the primary dataset were
unchanged throughout the optimization.

All **215 normalized candidate response hashes** match the pre-fix run; all
215 control hashes also match. No HTTP failures, dataset drift or unstable
responses occurred. The previously documented cross-API content differences
remain; performance work does not silently change their semantics.
The [intermediate run](comparison-results/2026-10-31-after-optimization.json),
[final query plans](comparison-results/performance-plans-after.txt) and
[machine-readable summary](comparison-results/performance-optimization-summary.json)
retain the evidence and raw timings.

SQL regression checks compare the complete neutral-loss multiset, metadata
aggregates and names, including invalid/single peaks, invalid/multiple precursors,
MS types and special characters. A real 677-record import with the final image
also completed successfully and refreshed the projections with no stale peak IDs.
The trade-off is derived storage and import-time work: the shared database grew
from approximately 1,409 to 2,064 MB (neutral-loss projection plus index: 488 MB;
names: 22 MB; metadata: 280 kB). There is still only one authoritative JPA dataset.

### Source fidelity: DATE and zero-valued peaks

Primary files, not legacy API output, are the correctness reference. The
[record format](https://github.com/MassBank/MassBank-documentation/blob/dev/MassBankRecordFormat.md)
and the three allowed DATE forms are mapped as follows:

| Source DATE | API `date` |
|---|---|
| `2012.10.22 (Created 2008.05.12)` | `{"updated":"2012-10-22","created":"2008-05-12"}` |
| `2016.01.19 (Created 2006.12.21, modified 2011.05.06)` | `{"updated":"2016-01-19","created":"2006-12-21","modified":"2011-05-06"}` |
| `2025.01.17` | `{"updated":"2025-01-17"}` |

The leading date does not establish a separate creation/modification history.
Only explicit historical dates are returned; missing values are omitted, not
replaced by year 0001 or copied from another date. Dates use the API's documented
`YYYY-MM-DD` format without an invented time or timezone. The frontend displays
the leading date and `N/A` for unavailable history; the export API retains the
complete original DATE text. Peak rows now explicitly retain zero-valued `mz`,
`intensity` and `rel` fields instead of dropping them through `omitempty`.
These intentional response changes follow the performance-only measurements
above; their unchanged-response hashes describe that earlier rollout.

The local snapshot at `9edb938bf5` contains 143,342 active and 234 deprecated
records. The parser accepted every active DATE, covering 107,085 plain dates,
7,855 with `Created` only and 28,402 with both historical fields. The real export
import parser also preserves all three forms unchanged.

The independent [primary-data checker](scripts/compare_primary_data.py) compares
DATE, copyright, compound classes, peak header/count and every numeric peak
value in each sampled full record. It ignores database-generated peak IDs, not
numeric precision, missing zero values or peak order. It is not a full-field or
exhaustive-record audit. Example:

```sh
python3 scripts/compare_primary_data.py \
  --source-data /path/to/MassBank-data \
  --source-reference 2026.03 \
  --sample-report comparison-results/2026-10-31-after-covering-indexes.json \
  --accession MSBNK-Osaka_Univ-OUF00405 \
  --accession MSBNK-Osaka_Univ-OUF01017 \
  --accession MSBNK-PFOS_research_group-FFF00074 \
  --output /tmp/primary-data-comparison.json
```

Exit status 1 reports a mismatch or HTTP error on either API, including existing
legacy differences. Invalid/missing source input fails explicitly before calls.
Both APIs are read-only during this check. Use the actual imported release as
the source reference; newer snapshots can contain genuine content changes.

After the software-only upgrade (Helm revision 14), **all 103 new-API records
match the original release-2026.03 files in every checked field**, with no HTTP
errors. The three DATE forms also render correctly in the browser with CSP
enabled. Counts, release and import timestamp are unchanged; no reimport ran.
The [before report](comparison-results/2026-10-31-primary-before-date-fix.json)
uses the local snapshot; the
[after report](comparison-results/2026-10-31-primary-after-date-fix.json)
uses original release files. The
[summary and source hashes](comparison-results/primary-data-fidelity-summary.json)
document the distinction: among these 103 records, only the class of
`MSBNK-mFam-MC23_000336` differs between those sources (`NA` in 2026.03 versus
`Sulfated steroids` in the newer snapshot). Both deployed APIs correctly retain
the release value; that is not a conversion defect.

The new API's split class lists, source-precision peak numbers, copyright and
peak headers are correct for these source records even where the old API differs.
Do not restore the old API's rounding or missing fields to obtain equality.

### Extended record-field comparison

Add `--all-fields` to the primary-data checker command above to also compare
accession/title, authors and MARC roles, license/publication/projects/comments,
compound names/formula/exact mass/structures/links, species information,
instrument and acquisition parameters, chromatography, focused-ion and
processing parameters, SPLASH and annotations. There are 39 comparison groups,
including the original checks, an active-record deprecation check and detection
of unmapped source tags. Source hashes are retained for every record.

The checker reconstructs AUTHORS text, requires literal string arrays for COMMENT,
transposes the API's
column-major annotations to source rows, and compares annotation m/z numerically.
Other annotation columns remain literal text. It preserves array order and
duplicates; order-only differences are explicitly identified. Legacy subtag
boundary differences that reconstruct the same complete line are marked
text-preserving, not confused with missing data. Optional absent source values
are compared with empty API containers/text.

The [extended report](comparison-results/2026-10-31-primary-all-fields.json)
and [findings summary](comparison-results/primary-all-fields-summary.json) cover
the same 103 original release-2026.03 records against the deployed APIs:
These are the findings **before the COMMENT correction below**.

| New API finding | Affected records | Interpretation |
|---|---:|---|
| Missing `comments` | 81 of 81 records containing COMMENT, 207 source lines | Confirmed content loss in the API response |
| Missing structured `marc-relator` | 3 of 3 records with explicit roles | Roles remain in `authors[].name`; structured field is not populated |
| `INTENSITY CUTOFF` subtag split | 2 | Full text is retained; not a lost processing value |

For example, `MSBNK-IPB_Halle-PB011601` contains
`COMMENT: CONFIDENCE Predicted` in both the original file and JPA document, but
the API omits `comments`. `ConvertMb2RecordToMb3Record` in
`MassBank3/pkg/mb3server/convert.go` writes the comments back to the input record
instead of assigning `result.Comments`.
For `MSBNK-EAWAG-EC103102`, `[dtc]`/`[com]` survive in the name strings, but
`ParseRecordAuthorNames` in `MassBank3/pkg/massbank/parser.go` does not extract
them into the dedicated role field. Both problems also occur in the old API.

The remaining populated field groups match in the new API, including all
annotations in 37 records. Overall, 22 of 103 new responses match every
comparison group; the other 81 have missing comments, with the role and
text-preserving split cases contained in that group. No HTTP errors occurred.
This comparison made **no application, deployment or database changes**;
the confirmed application defects are not fixed by this audit.

Coverage remains a sample, not all 139,006 records. Biological fields occur in
only 1-4 sampled records; projects in 4, publications in 35. No sampled source
contains AC$GENERAL or AC$ION_MOBILITY, so matching empty values are not proof
that these features work. Deprecated records, aggregate/search endpoints,
database-generated peak IDs and derived neutral losses are outside this audit.
The author's full text is checked, not an assumed unambiguous semantic split of
every name and affiliation.

### Exhaustive primary-data comparison

`scripts/compare_all_primary_data.py` checks **every accession**, not a sample.
It reuses the source-field mappings above and visits the union of all original
files and both APIs' complete `/records/search` inventories. Missing active
records, API-only accessions, duplicate inventory entries and count discrepancies
are reported explicitly. Use the actual installed release, not a newer snapshot:

```sh
python3 scripts/compare_all_primary_data.py \
  --source-data /path/to/original-release-2026.03 \
  --source-reference 2026.03 \
  --output /path/to/full-primary-comparison
```

By default this compares both public APIs. To select only the shared-database API,
add `--api new=https://msbi.ipb-halle.de/MassBank3-api`; `--api NAME=URL` is repeatable.
All source-backed active-record field groups are checked. Structured MARC roles
are excluded by default as unfinished functionality (`--include-marc-roles`
enables them); AUTHORS text is still compared. Deprecated source records are
also requested, with their accession, deprecation date and reason as reference.
An HTTP 200 containing an SQL error string is an error, never a successful match.

The output directory contains:

| File | Contents |
|---|---|
| `results.sqlite` | Transactionally saved result for each accession/API, including matches, errors, source SHA-256 and HTTP response hash |
| `differences.jsonl` | All differing/error cases, one JSON object per accession/API, with complete source/API values and exact paths |
| `summary.json` | Coverage, per-API outcomes, mismatching records per field/classification, example accessions and inventory stability |

JSONL and summary files are generated on completion or a controlled interruption.
SQLite progress is durable after each accession. Restart the same command with
`--resume` to process only unfinished accessions. Changed source hashes, API URLs,
inventories or comparison settings reject resumption. Previously recorded errors
are retained, not silently retried; use a fresh output directory for a new audit
after a deployment or data correction. Do not run two writers against one report.

Differences are **not truncated**: missing fields and array tails include their
values, long strings remain complete, and order/duplicates/whitespace are
preserved. Numeric values are parsed as exact decimals without a rounding
tolerance; diagnostic decimal values are serialized as strings to preserve their
precision. Order-only and text-preserving subtag-boundary differences are labeled
separately, not hidden. Generated peak IDs and derived search results have no
original-field equivalent and are outside this full-record audit.

The default is four concurrent accessions with a 50 ms pause before each request;
`--workers` and `--delay` control service load. Workers use separate persistent
HTTP connections; this is a correctness audit, not a latency benchmark. Input
processing and outstanding requests are bounded rather than retaining all
record bodies in memory. Large reports belong outside Git.

Exit codes: `0` complete and matching; `1` complete with differences/errors or an
unstable inventory; `2` incomplete/preflight failure. Inventories/counts are checked
again at the end. Stable inventories do not prove that values under existing
accessions stayed unchanged during a long run; avoid imports/deployments while
auditing, and retain the source release identifier.

### COMMENT correction

The API and frontend now use `comments` as an array of complete strings:

```json
{"comments":["CONFIDENCE Predicted","NATIVE_RUN_ID file.mzML"]}
```

`COMMENT` has no subtag/value structure. Prefixes, punctuation, whitespace,
order and repeated values remain intact. The Go converter now assigns the
response field rather than modifying its input. Internal/JPA decoding, OpenAPI
schemas and the frontend's single-column comment table agree on this contract;
absent comments still omit the optional field.

The software-only rollout uses API/frontend commit
`274cf472436e7a8214e71af46a4f23200a1838c5` (Helm revision 15).
The [after report](comparison-results/2026-10-31-primary-after-comment-fix.json)
and [summary](comparison-results/comment-fix-summary.json) confirm that all
**207 COMMENT values in 81 comment-bearing records** now match their original
2026.03 files. All 103 sampled database comment arrays also match the source;
the values were already stored correctly, so no database repair or reimport ran.
The release, 139,006 active records and original import timestamp are unchanged.

The filtered `/records?formula=C28H24O5` response also preserves comments in all
six records. Browser checks of PB011601 and IA000163 show the complete values
in the Comments section with CSP retained and no page errors.
[Open IA000163](https://msbi.ipb-halle.de/MassBank3/recordDisplay?id=MSBNK-ISAS_Dortmund-IA000163)
and select **Comments**.

There are no additional source-content differences in the 103-record rerun:
98 match every comparison group; three MARC-role differences are explicitly
out of scope, and two processing-subtag splits preserve the complete source
text. MARC handling and the old production API were not changed. The checker
still records these distinctions and legacy differences rather than hiding them.
Regression coverage includes literal string-array output, whitespace, duplicate
order, quoted text, legacy database encoding and frontend rendering.

### Full primary-data audit, 2026-10-31

The [complete summary](comparison-results/2026-10-31-full-primary-summary.json)
covers **139,240 accessions and 278,480 API responses**, using the original
2026.03 release at `705afb7bccc3b2c42410a744eef73674716a60ef`.
Both API inventories remained identical and stable: 139,006 active accessions,
no missing/extra accessions or duplicates. MARC roles were excluded.

| Shared API, active records | Records |
|---|---:|
| All compared fields match exactly | 137,450 |
| Only text-preserving `INTENSITY CUTOFF` subtag splits | 950 |
| Missing zero-intensity peak rows | 606 |

The 606 affected records are missing **680 complete peaks**, not just JSON
members. Their entire API peak arrays equal the original arrays after removing
rows whose intensity is zero. All other peak values and their order are retained.
The [detailed findings](comparison-results/full-primary-zero-intensity-findings.json)
list every affected accession: 597 RIKEN_NPDepo, five MSSJ and four HBM4EU records.
For example, HB002705 has 118 original peaks but only 105 in the API; the missing
rows include `74.0185 0 1`.

All 680 values **are present in the canonical JPA database**, in exactly the same
606 records. The cause is the `intensity > 0` predicate in the full-record view
`massbank_api.record_data`, defined in the export API's
`src/main/resources/shared-api.sql:124`. This is separate from the previously
fixed omission of zero-valued JSON members. This audit does not change the view,
deploy applications or reimport data.

COMMENT matches the original values throughout the new API's active records.
The old API differs in every active record; prominent field counts are DATE and
peak headers (139,006 each), peak values (131,073), missing COMMENT (114,190),
copyright (83,039), classes (61,135) and projects (6,685). These counts overlap
and describe differences, not uniformly data loss; the summary distinguishes
order-only changes.

Both APIs return HTTP 200 with the string `"sql: no rows in result set"` for all
234 deprecated accessions. These are recorded as errors, not matching records.
Exit status 1 therefore indicates a completed audit with findings, not an aborted
run. The full SQLite/JSONL evidence is retained outside Git in the session's
`files/full-primary-comparison-2026.03/` directory (approximately 2.3 GiB).

During evaluation, the checker was corrected to identify the numeric annotation
column by its `m/z` header rather than its position. Nine legacy responses were
reevaluated; all response SHA-256 hashes were identical to the original run.
Six apparent parser errors thereby became ordinary field differences. The
[reanalysis provenance](comparison-results/full-primary-annotation-reanalysis.json)
records those accessions; original results remain preserved alongside the full
evidence. The new API's findings were unaffected.

## Development Environment

A development container with Podman is configured under `.devcontainer/` providing all necessary tools for Helm chart development (`helm`, plugins `diff` and `unittest`, `kubectl`, `yq`, `kubeconform`, `helm-docs`, and `chart-testing`).

To open a shell or run commands inside the container using Podman:
```bash
./.devcontainer/run.sh
./.devcontainer/run.sh helm lint ./charts/massbank-frontend
```

See `.devcontainer/README.md` for complete documentation.

Opening the project in PyCharm does not start the devcontainer automatically. Open `.devcontainer/devcontainer.json` to create or connect to the devcontainer. The helper script above starts separate, disposable containers for commands and shells.
