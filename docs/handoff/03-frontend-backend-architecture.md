# 前后端实现说明

## 1. 技术栈

### 1.1 前端

- 原生 HTML
- 原生 CSS
- Vanilla JS module

### 1.2 后端

- Python 3 标准库
- `http.server`
- `urllib`
- `unittest`

## 2. 目录结构

```text
app/
  index.html
  styles.css
  app.js
  presentation.js
  demo-data.js

backend/
  server.py
  config.py
  providers.py
  engine.py
  rules.py
  tests/
```

## 3. 前端职责

### 3.1 `app/index.html`

- 页面骨架
- 输入区、结果区、详情区容器

### 3.2 `app/app.js`

- 前端状态管理
- `/api/search` 请求
- `/api/suggest` 请求
- 结果渲染
- demo 模式兜底

### 3.3 `app/presentation.js`

- 展示文案拼装
- 每段路线说明
- 截图清单
- 推荐时段说明
- 策略说明

## 4. 后端职责

### 4.1 `backend/server.py`

- 提供静态页面
- 提供 `/api/search`
- 提供 `/api/suggest`
- 提供 `/healthz`
- 支持环境变量控制监听地址和端口

### 4.2 `backend/config.py`

- 读取：
  - `COMMUTE_PROVIDER_MODE`
  - `AMAP_WEB_KEY`
  - `BAIDU_WEB_KEY`
  - `QQ_MAP_KEY`

### 4.3 `backend/rules.py`

- 按规则判断是否合规

### 4.4 `backend/engine.py`

- 汇总候选方案
- 计算总时长
- 按合规、段数、总时长做排序

### 4.5 `backend/providers.py`

- 地图请求封装
- 高德地点输入提示
- 高德 POI 搜索
- 高德步行 / 骑行 / 地铁路线
- 地铁站识别
- 同名门口 / 楼栋别名派生
- 多候选比较

## 5. 当前核心搜索策略

### 5.1 起终点候选

先建立两个精确点：

- 用户输入的房源
- 用户输入的公司

然后再派生少量高价值同名候选：

- 房源：`北门 / 南门 / 西门`
- 公司：`西塔 / 东塔 / T2栋`

### 5.2 模板集合

当前 `commute-r1.0` 支持：

- `walk`
- `bike`
- `subway`（地图端到端方案）
- `bike->subway->bike`

### 5.3 排序逻辑

排序优先级：

1. 是否属于合法模板并符合阈值
2. 段数更少
3. 总时长更短
4. 如果同分，再优先精确点而不是 alias

这意味着“有路线”与“系统合规”是两个状态；系统合规仍要回地图 App 复核。

示例：

- 直达骑行 18 分钟会排在三段混合 19 分钟前面
- 但如果 `北门 -> 西塔` 19 分钟，而原始点 20 分钟，那么会推荐 alias 方案

## 6. 当前部署接口

### 6.1 环境变量

- `COMMUTE_PROVIDER_MODE`
- `AMAP_WEB_KEY`
- `BAIDU_WEB_KEY`
- `QQ_MAP_KEY`
- `COMMUTE_SERVER_HOST`
- `COMMUTE_SERVER_PORT`

### 6.2 健康检查

- `GET /healthz`

返回：

```json
{
  "status": "ok",
  "service": "commute-combo"
}
```

## 7. 当前架构优点

- 无第三方后端框架，迁移成本低
- 本地调试简单
- 小范围部署简单
- 搜索和展示逻辑清晰分层

## 8. 当前架构缺点

- `ThreadingHTTPServer` 只适合轻量试用
- 没有缓存层
- 没有持久化日志
- 没有熔断与重试策略
- 地图提供商目前首版实用上基本以高德为主
