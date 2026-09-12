# 🎬 B站大会员点映会监控 - GitHub Actions & GitHub Pages 方案

本项目使用 GitHub Actions 定时运行监控脚本，抓取 B站 线下点映会数据，有新项目时通过 Bark 推送通知，并自动将看板部署到 GitHub Pages。

---

## 🚀 部署步骤

1. **新建或推送到 GitHub 仓库**：
   将当前文件夹下的所有内容推送到你的 GitHub 仓库（例如 `bili-dyh-monitor`）。
2. **配置 Bark 密钥 (GitHub Secret)**：
   - 进入仓库页 -> **Settings** -> **Secrets and variables** -> **Actions**。
   - 点击 **New repository secret**：
     - Name: `BARK_KEY`
     - Value: 填入你的 Bark 设备 Key（历史对话中的 `bXCfX...`）。
   - （可选）如 Bark 服务器不是 `https://bark.guoyingwei.top`，可在 **Variables** 中新增 `BARK_SERVER`。
3. **开启 GitHub Pages 权限**：
   - 进入 **Settings** -> **Pages**。
   - 在 **Build and deployment** 下的 **Source** 选择 **GitHub Actions**。
4. **运行与定时**：
   - 工作流已配置 `cron: '*/30 * * * *'`（每 30 分钟自动运行）。
   - 你也可以在 GitHub 的 **Actions** 标签页中找到 `B站大会员点映会监控与通知`，点击 **Run workflow** 手动触发第一次抓取与部署。
