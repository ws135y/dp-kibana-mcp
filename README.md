# Kibana 日志查询 MCP

这是一个只读 Python MCP 服务。它不连接生产 Elasticsearch，而是使用 Kibana 的已登录 `sid` Cookie 调用 `/internal/_msearch` 查询日志。

## 已提供工具

- `check_connection`：验证 Kibana 地址与登录态。
- `search_logs`：按关键词、时间范围、索引和精确字段查询，自动分页并去重。
- `get_trace_logs`：按 traceId 查询链路日志。
- `get_log_context`：查询某时间点前后的日志。
- `aggregate_logs`：按服务、级别、主机等字段统计。

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
search_logs(query="CO20260913BLQXX5O", start_time="now-1h", end_time="now", max_results=1000)
get_trace_logs(trace_id="0123456789abcdef0123456789abcdef", start_time="now-1d")
aggregate_logs(group_by="appname.keyword", query="Exception", start_time="now-2h")
```
