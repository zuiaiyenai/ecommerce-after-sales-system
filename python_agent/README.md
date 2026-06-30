# Python Agent

这个目录是当前 Spring Boot 项目内置的售后 AI Agent。

## 目录作用

- `web_demo.py`
  - Python Agent 的 HTTP 入口，默认监听 `127.0.0.1:8000`
- `after_sales_agent/`
  - 售后意图识别、状态推进、凭证审核、风险判断、转人工等核心逻辑
- `db.local.env`
  - Python Agent 连接 MySQL 的本地配置
- `sample_images/`
  - 图片审核联调样例图，仅用于 `/api/review-images` 售后凭证审核，不作为商品图片入库

## 启动方式

在当前仓库根目录执行：

```powershell
pip install -r python_agent\requirements.txt
powershell -ExecutionPolicy Bypass -File python_agent\run_agent.ps1
```

也可以进入 `python_agent` 目录后直接执行：

```powershell
python web_demo.py
```

## 联调关系

- 小程序/H5 只请求 Spring Boot：`/api/agent/*`
- Spring Boot 再代理到 Python Agent：`http://127.0.0.1:8000/api`

## 数据库说明

`after_sales_agent/db.py` 已支持自动查找以下任一配置文件：

- 仓库根目录下的 `db.local.env`
- `python_agent/db.local.env`
- 当前工作目录下的 `db.local.env`

当前默认数据库：

- Host: `localhost`
- Port: `3306`
- Database: `ecommerce_aftersales`
