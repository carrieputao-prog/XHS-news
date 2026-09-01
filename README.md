# XHS AI Hot Trends Bot

每日追踪最近 24 小时小红书 AI 类热门话题和低粉高互动笔记，并推送到钉钉。

## 环境变量

- `DASHSCOPE_API_KEY`
- `DINGTALK_WEBHOOK`
- `DINGTALK_SECRET`
- `GRAPE_DATA_TOKEN`：需要有 `carrieputao-prog/grape-data` 写权限的 GitHub token
- `QWEN_MODEL`：可选，默认 `qwen-plus`
- `DASHSCOPE_BASE_URL`：可选，默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`

本地运行时可直接设置 `GITHUB_TOKEN`。GitHub Actions 中建议使用 `GRAPE_DATA_TOKEN`，因为默认 `GITHUB_TOKEN` 通常不能写入其他仓库。

## 运行

```bash
python send_xhs_news.py daily
python send_xhs_news.py weekly
```

## 定时

- 每天北京时间 16:00：推送小红书 AI 热点追踪，并保存轻量结构化数据到 `grape-data/xhs-hot-trends/{date}.json`
- 每周五北京时间 10:00：读取本周结构化数据，筛选 AI 新词候选，写入 `grape-data/pending_topics.json`
