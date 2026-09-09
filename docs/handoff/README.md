# Commute Combo Handoff

- 文档日期：2026-08-02
- 项目目录：`/Users/dengzhilei/Documents/Codex/2026-08-01/ai`
- 当前交付形态：H5 + Python 轻后端，可本地运行，也可部署到云服务器做小范围试用

## 文档目录

1. [01-product-spec.md](./01-product-spec.md)
   项目目标、目标用户、痛点定义、MVP 范围、当前偏差
2. [02-design-and-user-flow.md](./02-design-and-user-flow.md)
   页面设计、交互流、结果展示逻辑、截图链路
3. [03-frontend-backend-architecture.md](./03-frontend-backend-architecture.md)
   前后端结构、关键模块、搜索与排序逻辑、部署接口
4. [04-validation-and-debug-log.md](./04-validation-and-debug-log.md)
   多轮调试、关键 bug、修复方式、当前遗留问题
5. [05-deployment-and-trial.md](./05-deployment-and-trial.md)
   云服务器试用方式、环境变量、上线前还缺什么
6. [06-next-window-handoff.md](./06-next-window-handoff.md)
   可直接带到新窗口继续做的接力说明

## 一句话结论

这个项目已经可以作为“给朋友试用”的公网 H5 工具部署到腾讯云服务器，但还不是稳定的正式生产版。当前最合适的定位是：

- 小范围试用
- 收集真实地址样本
- 验证“同名门口 / 楼栋别名比较”是否真的能提升命中房补范围的概率

## 当前最重要的事实

- 已支持高德主算路实时搜索
- 已支持高德地点候选下拉
- 已支持纯步行、纯骑行、步行/骑行 + 地铁 + 步行的方案
- 已支持同名门口 / 楼栋别名比较，例如 `中海雅园` 与 `中海雅园北门`
- 已支持结果说明、截图清单、推荐测距时段
- 已支持云服务器监听地址和健康检查：`COMMUTE_SERVER_HOST`、`COMMUTE_SERVER_PORT`、`/healthz`

## 当前不应对外夸大的能力

- 还没有做到“无限穷举所有可能门口、楼栋、站点”
- 还没有接入正式的持久化日志、缓存、账号体系
- 还没有做高并发生产架构
- 还没有形成匿名地址样本自测后的稳定策略库
