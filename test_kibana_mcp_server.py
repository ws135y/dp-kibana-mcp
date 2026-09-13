import json
import unittest

import kibana_mcp_server as server


class KibanaMcpServerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
