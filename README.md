# Kibana 日志查询 MCP

这是一个只读 Python MCP 服务。它不连接生产 Elasticsearch，而是使用 Kibana 的已登录 `sid` Cookie 调用 `/internal/_msearch` 查询日志。

## 已提供工具

- `check_connection`：验证 Kibana 地址与登录态。
- `search_logs`：按关键词、时间范围、索引和精确字段查询，自动分页并去重。
- `get_trace_logs`：按 traceId 查询链路日志。
- `get_log_context`：查询某时间点前后的日志。
- `aggregate_logs`：按服务、级别、主机等字段统计。
- `analyze_latency`：按服务、HTTP 方法、接口汇总响应次数和耗时，返回平均值、P50/P90/P95、最大值、状态码和最慢十条的 traceId。

所有请求仅发送到固定的 Kibana `POST /internal/_msearch`；服务不包含写入、删除或更新 ES 数据的能力。返回日志会隐藏 `sid`、Cookie、Token、Authorization、密码和 Secret 等字段。

Kibana 7.13 的 `/internal/bsearch` 会校验由浏览器生成的内部请求 `id`，普通 UUID 会被拒绝。此服务改用同样只读的 `/internal/_msearch`；该接口要求 JSON 的 `searches` 数组（不是 Elasticsearch 原生的 NDJSON 格式），因此不依赖这个动态且不应由 MCP 伪造的 `id`。

## 配置

复制 `.env.example` 的字段到 MCP 客户端的环境变量配置中。不要把真实 sid 写入代码、README 或 Git。

| 变量 | 说明 |
| --- | --- |
| `KIBANA_BASE_URL` | Kibana 地址，例如 `https://kibana.dragonpass.com.cn` |
| `KIBANA_SID` | 登录 Kibana 后 Cookie 中 `sid=` 后面的值，不要包含 `sid=` 前缀 |
| `KIBANA_VERSION` | Kibana 版本，当前为 `7.13.0` |
| `KIBANA_DEFAULT_INDEX` | 默认日志索引，例如 `logstash-filebeat-*` |
| `KIBANA_TIMEOUT_SECONDS` | 请求超时秒数，默认 15，最大 60 |

`sid` 到期时，工具会返回“登录态无效或已过期”。在 MCP 客户端更新 `KIBANA_SID` 后重启该 MCP 服务即可。

## 安装与本地验证

```powershell
cd D:\pyProject\kibana-mcp
python -m pip install -r requirements.txt
python -m unittest -v
python -B smoke_test_mcp.py
```

## Codex MCP 配置示例

启动命令：

```text
python
```

参数：

```text
D:\pyProject\kibana-mcp\kibana_mcp_server.py
```

环境变量：

```text
KIBANA_BASE_URL=https://kibana.dragonpass.com.cn
KIBANA_SID=<只填 sid 的值>
KIBANA_VERSION=7.13.0
KIBANA_DEFAULT_INDEX=logstash-filebeat-*
KIBANA_TIMEOUT_SECONDS=15
```

## 查询示例

```text
search_logs(query="CO20260913BLQXX5O", start_time="now-1h", end_time="now", max_results=5000)
get_trace_logs(trace_id="0123456789abcdef0123456789abcdef", start_time="now-1d")
aggregate_logs(group_by="appname.keyword", query="Exception", start_time="now-2h")
analyze_latency(query="/cms/customer/decryptValue", filters={"appname.keyword": "customer-sys-api"}, start_time="2026-10-03T18:30:00+08:00", end_time="2026-10-03T19:00:00+08:00")
```

## 分页及完整性

查询采用兼容 Kibana 7.13 的 `from + size` 分页。`size` 是每页条数，最多 200；`max_results` 是本次总条数上限，默认和最大值均为 **5000**。超过 1000 条会继续查询后续页，直到取完或达到本次上限。调用方仍可显式设置较小的 `max_results`。

结果包含 `total`（匹配日志数）、`returned`、`pages`、`max_results`、`truncated`、`timed_out`、`complete` 和 `warnings`。超过本次上限时，返回 `truncated=true` 和不完整结果提示；查询超时也会标记 `complete=false`。超过 5000 条需要缩小时间范围或增加服务等过滤条件。分页不是固定快照，查询期间新增日志可能影响跨页结果。

## 接口耗时汇总

`analyze_latency` 使用相同的分页逻辑，但仅返回统计和最慢请求的摘要，不返回原始日志正文。它从 `REP <bytes>b <status> <duration>ms <method> <path>` 格式解析耗时，忽略请求日志和其他格式。接口查询参数不参与分组；所有耗时单位均为毫秒。P50/P90/P95 使用 nearest-rank 方法（排序后取向上取整的分位位置）。

`response_count` 是已解析的响应记录数，并不包含没有响应日志的请求；HTTP 错误响应也计入统计。`groups` 按服务、请求方法和接口分组，`overall` 是所有已解析响应的汇总，`slowest` 提供最慢十条的时间、服务、接口、耗时和 traceId。`slow_threshold_ms` 默认 1000，`slow_count` 统计耗时大于等于该阈值的响应。

`total_logs` 和 `scanned_logs` 表示匹配及已读取的日志条数，上限 5000 包含非响应日志。`complete=false` 时统计仅基于已读取部分；`complete=true` 也仅表示匹配日志已取完，不保证每个请求都有可解析的响应记录。服务调用之间的耗时可能重叠，不能直接把各服务耗时相加作为端到端耗时。

修改代码后，需重启/重新连接 MCP 服务以加载新的工具和默认分页上限。
