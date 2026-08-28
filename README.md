# Atour · 亚朵酒店全国比价工具（统一项目）

> **⚠️ 重要：使用、开源或部署本项目前，请务必先阅读 [DISCLAIMER.md](./DISCLAIMER.md)。**
> 本项目基于亚朵**非官方接口**（逆向 App 得到）实现房价查询，仅供**个人学习研究**，存在合规与法律风险，作者不对任何商业化/规模化使用负责。

将**起始页**（Astro 静态站点）与**结果页**（Streamlit 数据应用）整合到一个项目目录中，一键启动。

## 目录结构

```
atour-project/
├── config.yaml.example # 全局配置模板（复制为 config.yaml 使用；config.yaml 不纳入版本控制）
├── .gitignore          # 已忽略 token 配置、venv、node_modules、构建产物
├── LICENSE             # MIT
├── start.sh            # 一键启动（Git Bash / macOS / Linux）
├── start.bat           # 一键启动（Windows 双击）
├── stop.sh             # 停止服务
├── README.md
├── DISCLAIMER.md       # 免责声明（务必阅读）
├── frontend/           # 起始页（Astro + WebGL 动画背景）
│   ├── src/            # 页面/组件/布局/脚本/样式
│   ├── public/         # 静态资源（含亚朵官方城市数据 atour-cities.json）
│   ├── package.json
│   ├── .env.example    # 前端构建环境变量模板（RESULT_APP_URL）
│   └── astro.config.mjs
└── backend/            # 结果页（Streamlit）
    ├── app.py          # 主应用（查询表单 + 地图 + 酒店列表）
    ├── services/atour_api.py   # 亚朵官方接口封装（自动读取 config.yaml）
    ├── requirements.txt
    └── .venv/          # Python 虚拟环境（首次启动自动创建）
```

## 快速启动

**Windows**：双击 `start.bat`

**或命令行**：
```bash
bash start.sh
```

启动后：
- **起始页**：http://localhost:4321/ 
- **结果页**：http://localhost:8501/ 
从起始页选择城市/省份、日期，点击「查询酒店价格」即跳转到结果页展示比价。

## 端口

| 服务 | 默认端口 | 环境变量 |
|------|----------|----------|
| Astro 起始页 | 4321 | `ASTRO_PORT` |
| Streamlit 结果页 | 8501 | `STREAMLIT_PORT` |

## 首次启动自动完成
- 前端：`npm install` 安装 Astro + three.js 依赖，然后构建静态站点。
- 后端：创建 `.venv` 虚拟环境并安装 streamlit / pandas / requests / pypinyin。

## 亚朵官方城市数据

`frontend/public/atour-cities.json` 来自亚朵官方接口 `/atourlife/city/listOfChain`
（31 省 / 262 城）。如需更新，可在 `backend` 中执行：

```python
from services.atour_api import get_atour_cities, ATOUR_TOKEN
import json
json.dump(get_atour_cities(ATOUR_TOKEN, force=True),
          open('../frontend/public/atour-cities.json', 'w', encoding='utf-8'),
          ensure_ascii=False)
```

> token 留空（`atour_token: ""`）= 未登录模式：未登录状态下
> 酒店列表/房型报价接口均正常返回完整数据，无需登录即可查询。

## 配置说明（config.yaml）

> `config.yaml` **不纳入版本控制**（已在 `.gitignore` 忽略），部署时请复制 `config.yaml.example` 为 `config.yaml` 后填写。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `token.atour_token` | 亚朵会员 token（请求 URL 中的 token 参数）；**留空 = 未登录模式** | 空（未登录） |
| `request.list_delay.min/max` | 列表请求每页间的随机节流区间（秒） | 0.3 / 0.5 |
| `request.light_delay.min/max` | 酒店详情/房型等轻量请求的随机节流区间（秒） | 0.25 / 0.6 |
| `request.retry_backoff` | 失败重试退避系数（第 N 次重试前 sleep = 系数 × N 秒） | 1.5 |

> 数值越小查询越快，但越容易被接口限流；被限流时适当调大。
> 也可用环境变量 `ATOUR_CONFIG` 指定配置文件的绝对路径（默认自动定位项目根目录 `config.yaml`）。

## 部署上线

本项目由两个独立服务组成，可分别部署：

```
浏览器
  │  GET /  （带 ?location=&check_in=&check_out= 等参数）
  ▼
[前端] Astro 静态站（GitHub Pages / Netlify / Vercel / 任意静态托管）
  │  通过 RESULT_APP_URL 配置的地址跳转
  ▼
[后端] Streamlit 应用（Streamlit Community Cloud / Render / VPS）
  │  读取 config.yaml，调用亚朵接口
  ▼
亚朵接口
```

### 1. 后端（Streamlit）部署

**推荐：Streamlit Community Cloud（免费）**
1. 把项目推到 GitHub（见下方「推送到 GitHub」）。
2. 登录 https://share.streamlit.io ，点 **New app**。
3. 选择仓库，关键配置：
   - **Main file path** 填 `backend/app.py`
   - **Python version** 选择 3.10 或更高
   - 依赖将自动读取 `backend/requirements.txt`
4. 部署完成后会得到一个形如 `https://your-app.streamlit.app/` 的地址，记下来。

> **关键点**：入口必须是 `backend/app.py`，这样 `from services.atour_api import ...` 才能正确解析。
> 若部署环境缺少 `config.yaml`，后端会自动以「未登录模式」运行（等价于 token 为空）。

### 2. 前端（Astro）部署

**推荐：GitHub Pages（免费，与仓库直连）**
1. 构建静态产物：`cd frontend && npm install && npm run build`，产物在 `frontend/dist/`。
2. 部署时注入环境变量 `RESULT_APP_URL` 为第 1 步得到的后端地址：
   ```bash
   # 例如（按你的托管平台方式注入）：
   RESULT_APP_URL=https://your-app.streamlit.app/ npm run build
   ```
3. 把 `frontend/dist/` 上传到你选择的主机（GitHub Pages / Netlify Drop / Vercel CLI）。

> 若用 GitHub Actions 自动化：构建时读取仓库 Secrets 中的 `RESULT_APP_URL` 即可。
> 本地开发未设置该变量时，默认跳转 `http://localhost:8501/`。

### 3. 连接前后端

确保前端构建时 `RESULT_APP_URL` 指向真实可访问的后端 URL，然后访问前端地址即可完成「查询 → 跳转后端展示结果」的完整流程。

### 部署注意事项（合规与安全）

- **不要**把含 token 的 `config.yaml` 提交进仓库（已由 `.gitignore` 兜底）。
- 公开部署等于对亚朵非官方接口做**公开访问**，**接口可能随时限流/失效**，请控制请求频率，并阅读 `DISCLAIMER.md`。
- 地图瓦片使用高德/Apple MapKit 公共服务，若启用 MapKit 需自行申请 `MAPKIT_TOKEN`（默认回退到高德瓦片，无需 key）。

## 停止服务

```bash
bash stop.sh
```
或直接关闭对应的 cmd 窗口。

## 推送到 GitHub

```bash
# 1. 在项目根目录初始化并提交
git init
git add .
git commit -m "feat: init Atour price comparison tool"

# 2. 在 GitHub 网页上新建一个空仓库（不要勾选添加 README/.gitignore/LICENSE）
#    然后关联并推送（把 USERNAME/REPO 换成你的信息）
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

> 推送前请确认 `git status` 中没有 `config.yaml`、`node_modules/`、`.venv/`、`dist/` 被追踪（`.gitignore` 已处理）。

## License

[MIT](./LICENSE) © Atour Collection contributors

## 免责声明

见 [DISCLAIMER.md](./DISCLAIMER.md)。本项目与亚朵集团无任何隶属关系，数据仅供学习研究参考。
