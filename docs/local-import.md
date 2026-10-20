# 本地素材导入（含 TikTok）

基线提交：e91b291ddd7e135715699e7b6ffdefd4349ccf5e。此次提供后端 API；首页上传表单不在本次最小改造范围。

## 源码与数据结构检查

项目没有数据库：DATA_DIR/<task_id>/ 保存视频、detail.json、frames/、result.json；任务队列存在进程内存。原入口 /api/analyze 接收 url 和可选抖音 detail；downloader 返回 VideoMeta 并写 video.mp4。后续 pipeline 只需要这两项，适合注入已导入素材。FullAnalysisResult、SSE 与前端分析结果页可继续复用。

新增 import.json 保存 schema_version、标准化 video_meta、language、授权声明、SHA-256、文件大小、是否有音轨。VideoMeta 只增可选来源和指标字段，旧结果仍可读取。缺失指标为 null，真实 0 不改成未知；不把第三方视频入口当 TikTok video ID。

原抖音下载流程保留；TikTok URL 在任务创建前明确返回 422，避免进入错误的 aweme 下载流程。原 UI 已接受 TikTok 文本但没有实现下载，这次后端给出明确导入指引。

## 安装与启动

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# 使用抖音下载时才需要安装浏览器：playwright install chromium
uvicorn main:app --host 127.0.0.1 --port 8000
```

需要系统 ffmpeg、ffprobe。Whisper 在首次实际分析时可能下载模型；仅导入不会下载模型或访问模型 API。

## 1. 仅导入，不启动分析

保存 metadata.json（示例统计来自用户提供的第三方监测描述，未重新验证）：

```json
{
  "platform": "tiktok",
  "title": "Lewkin 牛仔裤穿搭",
  "views": 660000,
  "likes": 112000,
  "metrics_source": "vid2prompt 第三方监测邮件，2026-10-18",
  "metrics_are_estimates": true,
  "language": null,
  "rights_confirmed": true,
  "rights_note": "请替换为实际授权依据或自有素材说明"
}
```

```bash
curl --fail-with-body http://127.0.0.1:8000/api/imports \
  -F 'file=@./authorized-video.mp4;type=video/mp4' \
  -F 'metadata=<./metadata.json'
```

201 返回 import_id、status=imported 和完整 manifest。文件名不参与路径生成。以实际 ffprobe 时长为准，不接受侧录 duration。仅接受 FFprobe 识别的 MP4 容器，不做转码；建议浏览器兼容的 H.264/AAC。默认上限 500 MiB、600 秒，可通过 MAX_IMPORT_BYTES、MAX_IMPORT_DURATION 配置。分块检查大小并清理失败目录；探测 30 秒超时。探测及 FFmpeg 禁止网络协议。

metadata 必须为 JSON 对象；额外字段、负计数、字符串计数和缺少授权声明返回 422。source_url 只存储不抓取；可选 source_video_id、author、author_id、comments、shares、metrics_observed_at（ISO 8601）。language=null 自动识别，也可显式传 en/zh 等 Whisper 支持的语言码。授权声明用于记录，并不代替真实许可。

## 2. 显式启动分析（会调用现有模型）

**以下命令会触发实际模型调用；本次开发测试未执行。**

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/api/imports/IMPORT_ID/analyze \
  -H 'Content-Type: application/json' -d '{"allow_paid_models":true}'
```

202 返回 task_id=import_id、status=queued。省略确认或 false 返回 409；同一进程重复提交返回 409；不存在或非法 ID 返回 404。新建任务复用原 pipeline，跳过 downloader；不复制下游分析实现。抖音原入口的既有执行语义不变。

- 进度：GET /api/analyze/TASK_ID/stream
- 结果：GET /api/results/TASK_ID
- 视频：GET /api/video/TASK_ID
- 结果页：http://localhost:3000/analysis/TASK_ID

无音轨返回空 transcript，继续视觉分析。抖音默认中文保留；导入视频默认自动检测语言。音乐视频不等于无语音，Whisper 自身仍可能出现识别误差。

## 测试（不需要模型权重和 API key）

```bash
python -m unittest discover -s tests -v
```

测试用 FFmpeg 合成蓝色视频：验证真实导入/抽帧、无音轨、文件完整性、元数据、错误清理、上传上限、显式付费开关、重复提交、语言透传、导入与抖音两个流水线分支和原抖音 API。所有模型及网络下载均 mock；未验证真实豆包响应、Whisper 准确率、真实抖音站点和真实 TikTok 素材。

## 官方 TikTok 接口调研（2026-10-20）

1. [Display API / video query](https://developers.tiktok.com/doc/tiktok-api-v2-video-query/)：OAuth 用户授权、video.list scope；校验视频属于授权用户，一次最多 20 个 ID。返回 title、description、duration、cover、share/embed URL 与互动计数，字段中没有原始视频下载地址。可作为创作者授权场景的元数据补充，不能据此下载任意第三方热视频。
2. [Research API FAQ](https://developers.tiktok.com/doc/research-api-faq/)：需满足资格、提交研究项目并获批；FAQ 明确商业用户/广告主/创作者不适用。统计存在延迟，不适合作为商业带货雷达的默认接口。
3. [Commercial Content API](https://developers.tiktok.com/docs/en/commercial-content-api-query-commercial-content)：针对商业内容库；此端点国家范围为 EEA（不含英国、瑞士）。内容 URL 不等于原视频文件获取授权，也不是全量 TikTok 热榜接口。
4. [Data Portability API](https://developers.tiktok.com/doc/data-portability-api-get-started/)：应用及 Login Kit 审核、用户授权后申请导出，按异步请求生命周期取回数据。适合授权用户数据迁移，不能当任意第三方素材下载接口。

本次没有添加凭证配置或冒充可用的 TikTok 下载器。下一阶段应先具备审核通过的应用与创作者授权，再以 Display API 补全对应素材的元数据：id→source_video_id、share_url→source_url、like_count→likes、view_count→views 等，并标记 metrics_source、观测时间。官方 OAuth 凭证应留在服务端。视频文件仍走有权获取的素材交付路径。

## 范围与限制

此版本适用于单进程本地服务，继承原项目的内存队列、SSE 单消费者和任务失败后需重新导入等限制，重启后不会自动恢复任务。未增加鉴权、跨 worker 锁和任务数据库。不要直接作为公开上传服务；反向代理应限制请求体（FastAPI multipart 解析发生在路由大小校验之前）。大视频写盘仍有同步 I/O，最小版未引入后台任务队列。上传只有容器检查，并未保证所有浏览器支持该文件的编码。前端新增元数据类型，尚未制作上传 UI。互动统计仅作内容筛选，不能推断销量或转化。
