import json
import unittest
from unittest.mock import patch

import kibana_mcp_server as server


class KibanaMcpServerTests(unittest.TestCase):
    @staticmethod
    def fake_search(total, timed_out=False):
        def run(**kwargs):
            start = kwargs["from_offset"]
            end = min(start + kwargs["size"], total)
            return {
                "timed_out": timed_out,
                "hits": {
                    "total": {"value": total},
                    "hits": [
                        {"_index": "test-index", "_id": str(i), "fields": {"message": ["test log"]}}
                        for i in range(start, end)
                    ],
                },
            }
        return run

    def test_extracts_common_internal_search_response_shape(self):
        raw = server._extract_raw_response(
            {"responses": [{"id": "request-1", "rawResponse": {"hits": {"total": {"value": 1}, "hits": []}}}]}
        )
        self.assertEqual(1, raw["hits"]["total"]["value"])

    def test_normalises_fields_and_redacts_sensitive_values(self):
        result = server._search_response(
            {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_index": "logstash-filebeat-1",
                            "_id": "1",
                            "fields": {
                                "message": ["Token: abc123"],
                                "@timestamp": ["2026-09-13T00:00:00.000Z"],
                            },
                        }
                    ],
                }
            }
        )
        self.assertEqual(1, result["total"])
        self.assertEqual("Token: [REDACTED]", result["logs"][0]["message"])
        self.assertEqual("2026-09-13T00:00:00.000Z", result["logs"][0]["@timestamp"])

    def test_builds_read_only_search_payload(self):
        params = server._build_params(
            index="logstash-filebeat-*",
            query="CO20260913BLQXX5O",
            start_time="now-1h",
            end_time="now",
            time_field="@timestamp",
            filters={"level.keyword": "ERROR"},
            size=50,
            source_fields=["@timestamp", "message"],
            sort_order="desc",
        )
        body = params["body"]
        self.assertEqual(50, body["size"])
        self.assertEqual("CO20260913BLQXX5O", body["query"]["bool"]["must"][0]["multi_match"]["query"])
        self.assertNotIn("script", body)
        self.assertNotIn("update", body)

    def test_builds_internal_msearch_payload_without_browser_request_id(self):
        params = server._build_params(
            index="logstash-filebeat-*",
            query="test",
            start_time="now-1h",
            end_time="now",
            time_field="@timestamp",
            filters=None,
            size=1,
            source_fields=["message"],
            sort_order="desc",
        )
        payload = json.loads(server._build_msearch_payload(params).decode("utf-8"))
        self.assertEqual("logstash-filebeat-*", payload["searches"][0]["header"]["index"])
        self.assertEqual("test", payload["searches"][0]["body"]["query"]["bool"]["must"][0]["multi_match"]["query"])
        self.assertNotIn("mcp-", json.dumps(payload))

    def test_builds_from_offset_for_next_page(self):
        params = server._build_params(
            index="logstash-filebeat-*",
            query="test",
            start_time="now-1h",
            end_time="now",
            time_field="@timestamp",
            filters=None,
            size=50,
            source_fields=["@timestamp", "message"],
            sort_order="desc",
            from_offset=50,
        )
        self.assertEqual(50, params["body"]["from"])
        self.assertEqual(1, len(params["body"]["sort"]))

    def test_default_search_continues_after_1000_hits(self):
        with patch.object(server, "_run_search", side_effect=self.fake_search(1205)) as search:
            result = server.search_logs(query="test", size=200)
        self.assertTrue(result["ok"])
        self.assertEqual(1205, result["returned"])
        self.assertEqual(1205, len({log["_id"] for log in result["logs"]}))
        self.assertEqual(7, result["pages"])
        self.assertEqual([0, 200, 400, 600, 800, 1000, 1200],
                         [call.kwargs["from_offset"] for call in search.call_args_list])
        self.assertEqual(1, len({call.kwargs["preference"] for call in search.call_args_list}))
        self.assertTrue(result["complete"])
        self.assertFalse(result["truncated"])
        self.assertEqual([], result["warnings"])

    def test_search_caps_at_5000_and_reports_partial_results(self):
        with patch.object(server, "_run_search", side_effect=self.fake_search(5201)) as search:
            result = server.search_logs(size=200, max_results=9000)
        self.assertEqual(5000, result["returned"])
        self.assertEqual(5201, result["total"])
        self.assertEqual(5000, result["max_results"])
        self.assertEqual(25, search.call_count)
        self.assertEqual(4800, search.call_args.kwargs["from_offset"])
        self.assertTrue(result["truncated"])
        self.assertFalse(result["complete"])
        self.assertTrue(result["warnings"])

    def test_smaller_explicit_limit_and_timeout_remain_visible(self):
        with patch.object(server, "_run_search", side_effect=self.fake_search(1205, timed_out=True)):
            result = server.search_logs(size=200, max_results=600)
        self.assertEqual(600, result["returned"])
        self.assertEqual(3, result["pages"])
        self.assertTrue(result["truncated"])
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["complete"])
        self.assertEqual(2, len(result["warnings"]))

    def test_latency_groups_responses_and_calculates_nearest_rank_percentiles(self):
        logs = [
            {"appname": "service-a", "traceId": f"trace-{i}", "@timestamp": "2026-10-03T10:30:00Z",
             "message": f"[INFO] REP 50b 200 {i * 100}ms POST /test?private=value <-- raw-private-body"}
            for i in range(1, 21)
        ]
        logs.extend([
            {"appname": "service-b", "message": "REP 20b 503 42.5ms GET /other <-- body"},
            {"appname": "service-a", "message": "REQ 50b POST /test --> body"},
            {"appname": "gateway", "message": "No REP duration here"},
        ])
        result = server._summarise_latency({
            "logs": logs, "total": 23, "returned": 23, "pages": 1,
            "truncated": False, "timed_out": False, "warnings": [],
        }, 1000)
        self.assertEqual(21, result["response_count"])
        self.assertEqual(2, result["skipped_logs"])
        first, second = result["groups"]
        self.assertEqual(("service-a", "POST", "/test"),
                         (first["appname"], first["method"], first["path"]))
        self.assertEqual(20, first["count"])
        self.assertEqual(1050, first["avg_ms"])
        self.assertEqual(1000, first["p50_ms"])
        self.assertEqual(1800, first["p90_ms"])
        self.assertEqual(1900, first["p95_ms"])
        self.assertEqual(2000, first["max_ms"])
        self.assertEqual(11, first["slow_count"])
        self.assertEqual({"503": 1}, second["status_counts"])
        self.assertEqual(1, result["overall"]["error_count"])
        self.assertEqual("trace-20", result["slowest"][0]["traceId"])
        self.assertEqual(10, len(result["slowest"]))
        self.assertTrue(result["complete"])
        self.assertNotIn("raw-private-body", json.dumps(result))
        self.assertNotIn("private=value", json.dumps(result))
        self.assertNotIn("logs", result)

    def test_latency_tool_preserves_partial_search_metadata(self):
        search_result = {
            "ok": True, "total": 6000, "returned": 1, "pages": 1, "max_results": 5000,
            "truncated": True, "timed_out": False, "warnings": ["partial"],
            "logs": [{"appname": "service", "message": "REP 5b 200 7ms POST /test"}],
        }
        with patch.object(server, "search_logs", return_value=search_result) as search:
            result = server.analyze_latency(query="/test", filters={"appname.keyword": "service"})
        self.assertEqual(5000, search.call_args.kwargs["max_results"])
        self.assertEqual({"appname.keyword": "service"}, search.call_args.kwargs["filters"])
        self.assertEqual(6000, result["total_logs"])
        self.assertFalse(result["complete"])
        self.assertTrue(result["truncated"])
        self.assertEqual(2, len(result["warnings"]))

    def test_latency_empty_results_and_invalid_threshold(self):
        empty = {"logs": [], "total": 0, "returned": 0, "pages": 1,
                 "truncated": False, "timed_out": False}
        result = server._summarise_latency(empty, 1000)
        self.assertEqual(0, result["response_count"])
        self.assertIsNone(result["overall"]["p95_ms"])
        self.assertTrue(result["warnings"])
        with patch.object(server, "search_logs") as search:
            self.assertFalse(server.analyze_latency(slow_threshold_ms=float("nan"))["ok"])
            self.assertFalse(server.analyze_latency(slow_threshold_ms=-1)["ok"])
            search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
