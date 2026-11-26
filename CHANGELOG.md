# Changelog

本文档记录 `RFQ Desk（通用询报价工作台）` 的主要版本变更，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本规范。

## [0.1.0] - 2026-11-26

### Added
- **通用 B2B 询报价工作台**：去除行业限定，支持通用 B2B 询价表头/单位/状态识别、Jev 收件箱分流、RAG 历史报价检索、行级原文溯源、人工审批工作流与格式化 Excel 导出。
- **批量操作与离线识别**：新增批量补充品相、通用询价表模板与离线待办提取。
- **容器化部署与 CI**：补齐 Docker Compose 生产部署配置、GitHub Actions CI（升级至 Actions v7）与新版品牌 Logo，同步部署至 `https://rfq.2222444.xyz/`。

### Fixed
- 修正 POSIX 环境下演示样例路径校验问题，完成后端安全加固、Excel 公式注入防护及桌面/移动端 UI 回归验证。
