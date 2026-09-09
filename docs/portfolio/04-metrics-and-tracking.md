# 指标体系与埋点字典

## 北极星指标

**有效测距完成率** = 同一 `request_id` 下“系统规则合规 + 地图 App 复核一致 + 截图方案可用”的搜索数 / 纳入分析的搜索数。

它比“有结果率”更接近产品价值，也避免把普通路线命中包装成房补成功。

## 指标树

- 输入与供给：搜索数、实时搜索成功率、地图请求次数、错误类型。
- 中间质量：路线返回率、系统合规率、Top-1 有效命中率、别名有效案例数。
- 复核质量：地图一致率、最优分钟差、截图可用率。
- 效率：人工 / 工具任务用时、人工尝试次数、P50/P95 搜索延迟。
- 护栏：**错误合规率**、站点 / 出入口错误数、工具偏短率、无结果率。

## 统一事件字段

每次搜索及后续事件使用：`request_id`、`anonymous_session_id`、`environment`、`app_version`、`rule_version`。搜索完成事件另含 `latency_ms`、`provider_request_count`、`result_type`、`best_template`、`alias_used`、`error_type`。

环境仅允许 `dev`、`test`、`demo`、`self_test`、`prod`。默认看板只显示 `self_test,prod`；旧事件缺少环境时视为 `legacy`，不进入默认看板；mock 强制记为 `demo`。

## 事件

| 事件 | 触发 | 关键字段 |
| --- | --- | --- |
| `search_submit` | 提交搜索 | 地址哈希、长度、统一上下文 |
| `search_completed` | 后端完成 | 延迟、请求数、结果类型、合规与别名字段 |
| `result_shown` | Top-1 展示 | 模板、时长、合规层级 |
| `result_reviewed` | 地图复核保存 | 复核结论、实际分钟、问题分类 |
| feedback row | 反馈保存 | helpful、主题备注、统一上下文 |
| experiment row | CASE 保存 | 人工 / 工具配对字段，不含地址 |

## 事实与结果边界

开发、测试、demo 数据只能验证埋点链路，不能作为用户行为或实验结果。当前尚无真实用户数据；`prod` 为空是事实，不应用 demo 填充。

