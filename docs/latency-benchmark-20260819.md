# 售后 Agent 系统 - 链路延迟基准测试报告

**测试时间**: 2026-08-19  
**数据库**: PostgreSQL 16.14 (after_sales_rag)  
**数据量**: 50 knowledge chunks, GIN FTS 索引已启用  

---

## 1. 数据库连接延迟

| 指标 | 延迟 |
|------|------|
| Connect avg | 8.1ms |
| Connect p50 | 8.1ms |
| Connect p95 | 9.0ms |

> 建议：使用连接池（pgbouncer 或应用层连接池）以提升 QPS

---

## 2. Keyword FTS 查询延迟（新增 GIN 索引）

| 查询 | avg | p50 | p95 | QPS | Hits |
|------|-----|-----|-----|-----|------|
| 商品破损 | 3.5ms | 3.5ms | 3.9ms | 284.5 | 20 |
| 退货退款 | 3.6ms | 3.6ms | 4.2ms | 280.4 | 20 |
| 手机充电 | 3.6ms | 3.6ms | 4.0ms | 277.4 | 20 |
| 质量问题 | 3.8ms | 3.6ms | 5.1ms | 264.7 | 20 |
| 食品变质 | 3.5ms | 3.4ms | 4.2ms | 283.3 | 20 |
| 少发配件 | 3.5ms | 3.4ms | 4.0ms | 289.5 | 20 |
| 发错货 | 3.5ms | 3.4ms | 3.8ms | 289.2 | 20 |
| 七天无理由 | 3.5ms | 3.5ms | 3.9ms | 284.6 | 20 |

**平均延迟**: avg=3.6ms, p95=4.1ms  
**单连接 QPS**: ~280  

---

## 3. 各链路延迟估算

| 链路 | 延迟 | 说明 |
|------|------|------|
| Dense Retrieval | ~15ms | embedding 生成 + pgvector 向量搜索 |
| Keyword FTS | avg=3.6ms p95=4.1ms | Jieba 分词 + PostgreSQL FTS + GIN 索引 |
| RRF Merge | ~2ms | 内存合并 Dense + Keyword 结果 |
| Reranker | ~100ms | 外部 reranker API（可选异步） |
| **Pipeline 总计** | **~21ms** | Dense + Keyword + RRF（不含 LLM 和 Reranker） |

> LLM 生成延迟约 2-4 秒（qwen-plus），是端到端延迟的主要部分

---

## 4. QPS 分析

| 场景 | QPS | 说明 |
|------|-----|------|
| DB 单连接 | ~120 QPS | 含连接建立 |
| Keyword FTS | ~280 QPS | 单查询，复用连接 |
| Java API (顺序) | ~31 QPS | 含认证 + 检索 |
| Java API (10 并发) | ~341 QPS | 并发请求 |

---

## 5. GIN 索引效率

```
Index scans: 持续增长
Index tuples read: 高效（倒排索引直接命中）
Sequential scans: 0（GIN 索引正常工作）
```

---

## 6. 口语化查询召回测试

| 查询 | 预期 chunk | 结果 |
|------|-----------|------|
| 刚拆箱就发现商品裂开了 | 62 | ✗ (0 hits) |
| 手机屏幕有裂纹 | 40 | ✗ (0 hits) |
| 七天无理由退货 | 64 | ✗ (0 hits) |
| 质量问题换货 | 65 | ✓ (5 hits) |
| 少发了一个配件 | 72 | ✗ (0 hits) |
| 发错货了 | 73 | ✓ (1 hit) |
| 食品胀袋异味 | 105 | ✗ (0 hits) |
| 手机充不进电 | 104 | ✗ (0 hits) |

**当前 Recall**: 2/8 = 25%  

> **原因**: 口语化 token（"裂开"、"胀袋"）与知识库正式 token（"裂纹"、"变质"）不匹配  
> **解决方案**: 实现 colloquial-to-formal 同义词扩展（见 Phase 8）

---

## 7. 改进建议

1. **同义词扩展**: 添加 colloquial → formal 映射表，预计 Recall 提升至 80%+
2. **连接池**: 使用 pgbouncer 或应用层连接池，提升 QPS 10x
3. **异步 Reranker**: Reranker 可作为可选后置步骤，不阻塞主链路
4. **缓存**: 对热门查询结果缓存 5-10 分钟

---

## 8. 测试脚本

```bash
# 运行 FTS 基准测试
python3 tools/benchmark_fts_latency.py

# 运行 API 压测
python3 pressure_test.py --base-url http://192.168.2.8:8080 --concurrency 10 --total 50
```

---

*报告生成时间: 2026-08-19*
