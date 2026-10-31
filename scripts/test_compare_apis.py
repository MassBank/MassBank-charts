import http.client
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from compare_apis import (
    Client, Response, comparison, differences, distribution, inventory, normalize, run, sample_accessions,
)


class ComparisonTests(unittest.TestCase):
    def test_search_order_is_ignored_but_duplicates_and_values_are_not(self):
        left = {"data": [{"accession": "B", "peakPairs": ["2_1", "3_1"]}, {"accession": "A"}]}
        right = {"data": [{"accession": "A"}, {"accession": "B", "peakPairs": ["3_1", "2_1"]}]}
        self.assertEqual(normalize(left, "/records/search?q=x"), normalize(right, "/records/search?q=x"))
        right["data"].append({"accession": "A"})
        self.assertNotEqual(normalize(left, "/records/search"), normalize(right, "/records/search"))

    def test_record_peak_order_null_and_missing_fields_are_preserved(self):
        endpoint = "/records/A"
        self.assertNotEqual(normalize({"peaks": [1, 2]}, endpoint), normalize({"peaks": [2, 1]}, endpoint))
        self.assertNotEqual(normalize({"names": None}, endpoint), normalize({"names": []}, endpoint))
        self.assertNotEqual(normalize({"value": None}, endpoint), normalize({}, endpoint))

    def test_only_documented_metadata_fields_are_ignored(self):
        old = {"version": "old", "timestamp": "yesterday", "spectra_count": 1}
        new = {"version": "new", "timestamp": "today", "spectra_count": 1}
        self.assertEqual(normalize(old, "/metadata"), normalize(new, "/metadata"))
        new["spectra_count"] = 2
        self.assertNotEqual(normalize(old, "/metadata"), normalize(new, "/metadata"))
        self.assertEqual(normalize(old, "/records/A"), old)

    def test_errors_cannot_compare_equal(self):
        response = Response(500, 10, 0, None, error="HTTP 500")
        self.assertFalse(comparison(response, response, "/records/count")["semantic_equal"])

    def test_json_and_semantic_equality_reported_separately(self):
        old = Response(200, 1, 1, "a", {"data": [{"accession": "B"}, {"accession": "A"}]})
        new = Response(200, 1, 1, "b", {"data": [{"accession": "A"}, {"accession": "B"}]})
        result = comparison(old, new, "/records/search")
        self.assertFalse(result["json_equal"])
        self.assertTrue(result["semantic_equal"])
        self.assertEqual(result["search_inventory"]["only_new"], [])

    def test_search_diagnostics_identify_extra_hits_without_shifted_list_noise(self):
        old = Response(200, 1, 1, "a", {"data": [{"accession": "B"}]})
        new = Response(200, 1, 1, "b", {"data": [{"accession": "A"}, {"accession": "B"}]})
        result = comparison(old, new, "/records/search")
        self.assertEqual(result["search_inventory"]["only_new"], ["A"])
        self.assertEqual(result["search_inventory"]["old_hits"], 1)
        self.assertEqual(result["search_inventory"]["new_hits"], 2)

    def test_difference_paths(self):
        result = list(differences({"a": [1], "b": None}, {"a": [2, 3]}))
        self.assertEqual([item["path"] for item in result], ["$.a", "$.a[0]", "$.b"])

    def test_stratified_sample_is_deterministic_and_unique(self):
        ids = [f"MSBNK-{contributor}-{number}" for contributor in ["A", "B", "C"] for number in range(10)]
        sample = sample_accessions(ids, 6, 42)
        self.assertEqual(sample, sample_accessions(list(reversed(ids)), 6, 42))
        self.assertEqual(len(set(sample)), 6)
        self.assertEqual({value.split("-")[1] for value in sample[:3]}, {"A", "B", "C"})
        self.assertEqual(len(sample_accessions(ids, 100, 42)), 30)

    def test_distribution_retains_errors_and_all_raw_samples(self):
        result = distribution([Response(200, i, 1, "x") for i in range(1, 21)]
                              + [Response(None, 999, 0, None, error="timeout")])
        self.assertEqual(result["median_ms"], 10.5)
        self.assertEqual(result["p95_ms"], 19)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(len(result["samples"]), 21)
        self.assertIsNone(distribution([])["median_ms"])

    def test_inventory_validates_shape_and_retains_duplicates(self):
        for data in [{}, {"data": []}, {"data": [None]}, {"data": [{}]}]:
            with self.assertRaises(ValueError):
                inventory(Response(200, 1, 1, "x", data))
        self.assertEqual(inventory(Response(200, 1, 1, "x", {"data": [{"accession": "A"}] * 2})), ["A", "A"])


class ClientTests(unittest.TestCase):
    def client(self, body=b'{"ok": true}', status=200, max_bytes=1024):
        client = Client("https://example.test/api", 1, 0, max_bytes)
        client.connection = Mock()
        response = client.connection.getresponse.return_value
        response.status = status
        response.read.return_value = body
        return client

    def test_reads_body_before_stopping_timer(self):
        client = self.client()
        with patch("compare_apis.time.perf_counter_ns", side_effect=[1000000, 6000000]):
            result = client.get("/status")
        self.assertEqual(result.milliseconds, 5)
        self.assertEqual(result.data, {"ok": True})
        self.assertIsNone(result.error)
        self.assertEqual(client.connection.request.call_args.args[:2], ("GET", "/api/status"))

    def test_invalid_json_http_error_oversize_and_connection_errors_are_explicit(self):
        for client in [self.client(b"no json"), self.client(status=503), self.client(max_bytes=1)]:
            self.assertIsNotNone(client.get("/status").error)
        client = self.client()
        client.connection.getresponse.side_effect = http.client.RemoteDisconnected("closed")
        self.assertIn("RemoteDisconnected", client.get("/status").error)
        client.connection.close.assert_called()

    def test_each_request_uses_a_fresh_connection_without_retries(self):
        client = self.client()
        client.get("/status")
        client.get("/status")
        self.assertEqual(client.connection.close.call_count, 2)
        self.assertEqual(client.connection.request.call_count, 2)
        self.assertEqual(client.connection.request.call_args.kwargs["headers"]["Connection"], "close")

    def test_rejects_credential_urls(self):
        with self.assertRaises(ValueError):
            Client("https://user:password@example.test/api", 1, 0, 1024)


class RunTests(unittest.TestCase):
    def run_fixture(self, mismatch=False):
        requests = []
        record = {
            "accession": "MSBNK-IPB_Halle-PB011601",
            "compound": {"formula": "C28H24O5", "names": ["example"], "mass": 440, "smiles": "C"},
            "peak": {"peak": {"values": [{"mz": 100}]}},
            "mass_spectrometry": {"focused_ion": [{"subtag": "PRECURSOR_M/Z", "value": "441"}]},
        }

        class FakeClient:
            def __init__(self, base, *args):
                self.side = base

            def get(self, endpoint):
                requests.append((self.side, endpoint))
                if endpoint == "/records/count":
                    data = 1
                elif endpoint == "/metadata":
                    data = {"version": "2026.03", "spectra_count": 1}
                elif endpoint.startswith("/records/search"):
                    data = {"data": [{"accession": record["accession"]}]}
                elif endpoint.startswith("/records/"):
                    data = {**record, "title": self.side if mismatch else "same"}
                elif endpoint.startswith("/records?"):
                    data = [record]
                else:
                    data = {}
                return Response(200, 10 if self.side == "old" else 20, 1, "sha", data)

            def close(self):
                pass

        args = SimpleNamespace(old="old", new="new", timeout=1, delay=0, max_response_mib=1,
                               expected_release="2026.03", all_records=False, samples=1, seed=1,
                               warmup=2, repeats=3)
        report = {}
        with patch("compare_apis.Client", FakeClient), patch("builtins.print"):
            code = run(args, report)
        return code, report, requests

    def test_end_to_end_alternating_order_and_warmup_exclusion(self):
        code, report, requests = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertTrue(report["summary"]["passed"])
        self.assertTrue(report["dataset"]["stable_during_run"])
        self.assertEqual([side for side, _ in requests[:6]], ["old", "new", "new", "old", "old", "new"])
        for case in report["cases"]:
            self.assertEqual(case["performance"]["old"]["successful"], 3)
            self.assertEqual(case["new_over_old_median_ratio"], 2)

    def test_content_mismatch_fails_run_without_stopping_other_cases(self):
        code, report, _ = self.run_fixture(mismatch=True)
        self.assertEqual(code, 1)
        self.assertIn("record:MSBNK-IPB_Halle-PB011601", report["summary"]["semantic_mismatches"])
        self.assertGreater(len(report["cases"]), 10)


if __name__ == "__main__":
    unittest.main()
