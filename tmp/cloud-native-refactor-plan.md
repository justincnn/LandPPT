# LandPPT 完全云原生改造方案

> 目标：将 LandPPT 从“可容器化单实例应用”改造成“可水平扩展、可观测、可恢复、存储解耦、任务解耦”的云原生 SaaS 架构。

## 1. 改造结论

LandPPT 当前已经具备 Docker Compose 和 Helm Chart 部署基础，但仍然强依赖本地文件系统、Web 进程内后台任务、本地启动锁和单副本 PVC。若要达到“完全云原生”，核心改造不是简单编写更多 Kubernetes YAML，而是完成以下解耦：

1. **Web 无状态化**：Web Pod 不保存关键业务文件和长任务状态。
2. **文件对象存储化**：上传、图片、导出结果、音视频、研究报告等统一存储到 S3/MinIO。
3. **任务队列化**：PPT 生成、导出、视频、音频等长任务由 Worker 执行。
4. **数据库迁移 Job 化**：启动迁移从 Web 进程中移除，改为 K8s Job/Helm Hook。
5. **配置 Secret 化**：配置、密钥、API Key 统一通过 ConfigMap、Secret 或 External Secrets 管理。
6. **可观测性标准化**：日志、指标、链路追踪、任务状态、资源用量可观测。
7. **部署 GitOps 化**：镜像版本固定、Helm values 分环境、CI/CD 自动发布。

---

## 2. 当前状态评估

### 2.1 已具备能力

当前项目已有：

- `Dockerfile`
- `docker-compose.yml`
- `helm/landppt/`
- PostgreSQL 支持
- Valkey/Redis 兼容缓存支持
- `/health` 健康检查
- Uvicorn 多 worker 支持
- 部分后台任务状态通过 Valkey 共享

### 2.2 当前云原生短板

| 问题 | 现状 | 云原生风险 |
|---|---|---|
| 本地文件依赖 | `/app/uploads`、`/app/temp`、`/app/research_reports`、`/tmp` | 多 Pod 文件不可见 |
| 导出文件本地化 | `FileResponse(local_path)` | 下载请求落到其他 Pod 会失败 |
| 图片缓存本地化 | `temp/images_cache` + 本地 index | 多副本缓存不一致 |
| 后台任务在 Web 内执行 | `asyncio.create_task` / 内置 BackgroundTaskManager | Pod 重启任务丢失，Web 被长任务拖垮 |
| 启动迁移本地锁 | `/tmp/landppt_migration.lock` | 多 Pod 并发迁移风险 |
| PVC RWO | 当前 Helm 使用 RWO PVC + `Recreate` | 无法真正多副本滚动扩容 |
| 镜像 tag 默认 latest | `bradleylzh/landppt:latest` | 发布不可追溯 |
| 内置 PostgreSQL/Valkey | Helm 可内置部署 | 生产高可用不足 |

---

## 3. 目标架构

### 3.1 总体架构

```text
                         ┌────────────────────┐
                         │       Client       │
                         └─────────┬──────────┘
                                   │ HTTPS
                         ┌─────────▼──────────┐
                         │ Ingress / Gateway  │
                         └─────────┬──────────┘
                                   │
                 ┌─────────────────▼─────────────────┐
                 │        LandPPT Web Deployment      │
                 │  FastAPI / Auth / API / Web UI     │
                 │  Stateless, replicaCount >= 2      │
                 └───────┬──────────────┬─────────────┘
                         │              │
             Query/Write │              │ Enqueue Task
                         │              │
              ┌──────────▼───┐     ┌────▼─────────────┐
              │ PostgreSQL   │     │ Valkey / Redis   │
              │ Metadata DB  │     │ Queue / Cache    │
              └──────────────┘     └────┬─────────────┘
                                         │ Consume Task
                              ┌──────────▼─────────────┐
                              │ LandPPT Worker         │
                              │ PPT/PDF/PPTX/Audio/Video│
                              │ replicaCount >= 1      │
                              └──────────┬─────────────┘
                                         │ Put/Get artifact
                              ┌──────────▼─────────────┐
                              │ S3 / MinIO / OSS       │
                              │ Uploads / Exports      │
                              │ Images / Reports       │
                              └────────────────────────┘
```

### 3.2 组件职责

| 组件 | 职责 |
|---|---|
| Web Pod | 接收请求、鉴权、查询项目、提交任务、返回任务状态、生成下载 URL |
| Worker Pod | 执行 PPT 生成、PDF/PPTX 导出、视频导出、音频生成、文件解析等长任务 |
| PostgreSQL | 用户、项目、幻灯片、模板、任务元数据、业务状态 |
| Valkey/Redis | 分布式缓存、Session cache、任务队列、任务锁、进度缓存 |
| S3/MinIO | 上传文件、图片缓存、导出结果、音视频、研究报告、临时可下载产物 |
| Migration Job | 数据库初始化、迁移、默认模板初始化、管理员初始化 |
| CronJob | 过期文件清理、任务清理、会话清理、配额统计 |

---

## 4. 改造目标分级

### 4.1 P0：生产单副本稳定

目标：保持当前单副本部署，但去除明显生产风险。

- 固定镜像 tag，不使用 `latest`
- 使用外部 PostgreSQL
- 使用外部 Valkey/Redis
- 配置备份策略
- Secret 不写入 values.yaml 明文
- 保持 `replicaCount: 1`

### 4.2 P1：文件存储解耦

目标：所有用户可访问的文件都进入对象存储。

- 新增 Storage 抽象层
- 支持 `local` 和 `s3` 两种 backend
- 导出结果不再只保存本地 path
- 下载接口支持 artifact key / presigned URL
- 图片缓存迁移到对象存储

### 4.3 P2：后台任务解耦

目标：文件型、可异步完成的长任务进入 Worker；需要与用户保持实时交互的流式生成任务保留在 Web。

- 引入任务队列
- Web 提交导出、音频、视频等文件型任务
- Worker 执行文件型长任务
- 任务状态统一写 PostgreSQL/Redis
- 任务结果统一写对象存储
- 大纲/幻灯片流式生成等 SSE/实时交互任务暂不一刀切队列化

### 4.4 P3：K8s 原生化

目标：Web 可多副本，Worker 可水平扩容。

- Web Deployment 多副本
- Worker Deployment 独立副本数
- HPA
- PDB
- NetworkPolicy
- ServiceMonitor

### 4.5 P4：SaaS 级可靠性

目标：当 LandPPT 进入正式 SaaS 运营阶段后，再逐步支持多租户、配额、审计、弹性扩容和故障恢复。本阶段不作为云原生基础改造的前置条件。

- 多租户隔离
- 用户存储配额
- 死信队列
- 审计日志
- OpenTelemetry
- 灾备和恢复演练

---

## 5. 代码层改造方案

## 5.1 新增统一 Storage 层

### 5.1.1 新增目录

```text
src/landppt/services/storage/
  __init__.py
  base.py
  local_storage.py
  s3_storage.py
  factory.py
  models.py
```

### 5.1.2 Storage 接口

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

class ArtifactStorage(ABC):
    @abstractmethod
    async def put_file(
        self,
        local_path: str,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        pass

    @abstractmethod
    async def put_bytes(
        self,
        data: bytes,
        key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        pass

    @abstractmethod
    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    async def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        pass
```

### 5.1.3 配置项

在 `src/landppt/core/config.py` 增加：

```env
STORAGE_BACKEND=local              # local / s3
LOCAL_STORAGE_ROOT=/app/data/artifacts
LOCAL_STORAGE_PUBLIC_BASE_URL=

S3_ENDPOINT_URL=http://minio:9000
S3_REGION=us-east-1
S3_BUCKET=landppt
S3_ACCESS_KEY_ID=xxx
S3_SECRET_ACCESS_KEY=xxx
S3_FORCE_PATH_STYLE=true
S3_PUBLIC_BASE_URL=
S3_PRESIGNED_URL_EXPIRES_SECONDS=3600
```

### 5.1.4 对象 key 规范

```text
users/{user_id}/projects/{project_id}/uploads/{upload_id}/{filename}
users/{user_id}/projects/{project_id}/exports/{task_id}/{filename}
users/{user_id}/projects/{project_id}/narration/audio/{task_id}.{ext}
users/{user_id}/projects/{project_id}/narration/video/{task_id}.mp4
users/{user_id}/projects/{project_id}/reports/{report_id}.md
users/{user_id}/images/{cache_key}.{ext}
system/templates/{template_id}/assets/{filename}
```

### 5.1.5 需要优先替换的位置

| 位置 | 当前行为 | 改造后 |
|---|---|---|
| `web/route_modules/export_routes.py` | 本地临时文件 + `FileResponse` | 生成后上传 S3，返回 artifact key |
| `web/route_modules/narration_routes.py` | `uploads/narration_refs` 本地路径 | 存储到对象存储 |
| `services/image/cache/image_cache.py` | `temp/images_cache` 本地缓存 | 图片文件进 S3，元数据进 DB/Redis |
| `main.py` | `app.mount('/temp')` | 改为 `/api/assets/{asset_id}` 或 presigned URL |
| `project_workspace_routes.py` | `/temp/{file_path}` 本地文件 | artifact 下载接口 |

---

## 5.2 文件下载接口改造

### 5.2.1 当前问题

当前多处使用：

```python
return FileResponse(local_path)
```

这要求下载请求必须落在拥有该文件的 Pod 上。

### 5.2.2 目标接口

统一使用：

```text
GET /api/artifacts/{artifact_id}/download
GET /api/artifacts/{artifact_id}/url
```

其中 `artifact_id` 对应数据库表记录，而不是本地 path。

### 5.2.3 新增 artifact 表

```sql
CREATE TABLE artifacts (
  id UUID PRIMARY KEY,
  user_id BIGINT NOT NULL,
  project_id VARCHAR NULL,
  task_id VARCHAR NULL,
  artifact_type VARCHAR NOT NULL,
  storage_backend VARCHAR NOT NULL,
  storage_key TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type VARCHAR NULL,
  size_bytes BIGINT NULL,
  checksum_sha256 VARCHAR NULL,
  expires_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_artifacts_user_id ON artifacts(user_id);
CREATE INDEX idx_artifacts_project_id ON artifacts(project_id);
CREATE INDEX idx_artifacts_task_id ON artifacts(task_id);
```

### 5.2.4 下载策略

- 小文件：FastAPI `StreamingResponse`
- 大文件：返回 S3 presigned URL
- 私有文件：下载前校验 `user_id`
- 公开分享：生成受限 token 或只读 presigned URL

---

## 5.3 后台任务队列化

### 5.3.1 推荐技术选型

LandPPT 是 FastAPI + asyncio 项目，推荐优先使用：

- **arq**：Redis/Valkey 后端，asyncio 原生，轻量
- 备选：Dramatiq、Celery、RQ

推荐：**arq + PostgreSQL 任务表 + Valkey 队列**。

### 5.3.2 新增模块

```text
src/landppt/tasks/
  __init__.py
  queue.py
  models.py
  registry.py
  worker.py
  handlers/
    export_pdf.py
    export_pptx.py
    export_html.py
    generate_slides.py
    regenerate_slides.py
    narration_audio.py
    narration_video.py
    speech_script.py
```

### 5.3.3 任务状态表

```sql
CREATE TABLE async_tasks (
  id UUID PRIMARY KEY,
  task_type VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  user_id BIGINT NOT NULL,
  project_id VARCHAR NULL,
  progress DOUBLE PRECISION NOT NULL DEFAULT 0,
  input JSONB NOT NULL DEFAULT '{}',
  result JSONB NULL,
  error TEXT NULL,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  locked_by VARCHAR NULL,
  started_at TIMESTAMP NULL,
  finished_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_async_tasks_user_id ON async_tasks(user_id);
CREATE INDEX idx_async_tasks_project_id ON async_tasks(project_id);
CREATE INDEX idx_async_tasks_status ON async_tasks(status);
```

### 5.3.4 任务状态流转

```text
pending -> queued -> running -> completed
                         └──> failed
                         └──> retrying -> queued
                         └──> cancelled
```

### 5.3.5 Web 提交任务

```python
task = await task_service.create_task(
    task_type="export_pdf",
    user_id=user.id,
    project_id=project_id,
    input={"individual": False},
)
await queue.enqueue("export_pdf", task_id=str(task.id))
return {"task_id": str(task.id), "status": "queued"}
```

### 5.3.6 Worker 执行任务

```python
async def export_pdf(ctx, task_id: str):
    task = await task_service.mark_running(task_id)
    try:
        local_path = await generate_pdf_to_temp(task.input)
        artifact = await artifact_service.save_file(
            local_path=local_path,
            user_id=task.user_id,
            project_id=task.project_id,
            task_id=task_id,
            artifact_type="pdf_export",
        )
        await task_service.mark_completed(task_id, result={"artifact_id": artifact.id})
    except Exception as exc:
        await task_service.mark_failed(task_id, str(exc))
        raise
```

### 5.3.7 需要迁移的任务

优先迁移“执行时间长、产出文件、用户可异步等待”的任务。大纲生成、幻灯片流式生成等需要 SSE/实时进度交互的流程，短期保留在 Web 进程中，后续再按实际瓶颈拆分。

| 任务 | 当前位置 | 目标 handler |
|---|---|---|
| PDF 导出 | `export_routes.py` | `tasks/handlers/export_pdf.py` |
| PPTX 导出 | `export_routes.py` | `tasks/handlers/export_pptx.py` |
| HTML 导出 | `export_routes.py` | `tasks/handlers/export_html.py` |
| 讲解音频 | `narration_routes.py` | `tasks/handlers/narration_audio.py` |
| 讲解视频 | `narration_routes.py` / `video_export_service.py` | `tasks/handlers/narration_video.py` |
| 批量幻灯片重生成 | `slide_routes.py` | 后续评估，若非流式交互再迁移 |
| 演讲稿生成 | `speech_script_routes.py` | 后续评估，保留实时交互优先 |
| PPT 全量生成 | slide services | 暂不一刀切迁移，流式生成保留在 Web |

---

## 5.4 数据库迁移 Job 化

### 5.4.1 当前问题

当前启动初始化逻辑位于：

```text
src/landppt/database/startup_initialization.py
src/landppt/database/startup_migrations.py
```

并且使用 `/tmp` 文件锁。该锁只能在同一个 Pod 内有效，不能跨 Pod。

### 5.4.2 目标

该项应提前到基础稳定化之后实施，而不是等到 Helm Web/Worker 拆分完成。迁移 Job 化改动相对独立，却是 Web 多副本和安全升级的前提。

生产环境关闭 Web 启动迁移：

```env
LANDPPT_AUTO_MIGRATE_ON_STARTUP=false
```

新增 CLI：

```bash
python -m landppt.cli migrate
python -m landppt.cli bootstrap-default-templates
python -m landppt.cli bootstrap-admin
```

### 5.4.3 Helm Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: landppt-migrate
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: migrate
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          command:
            - python
            - -m
            - landppt.cli
            - migrate-and-bootstrap
          envFrom:
            - configMapRef:
                name: landppt
            - secretRef:
                name: landppt
```

---

## 5.5 Web 无状态化

### 5.5.1 Web Pod 不再挂载业务 PVC

目标 Web Pod 只需要：

- 只读代码和静态资源
- `/tmp` emptyDir 用于短生命周期临时文件
- 通过 DB/Redis/S3 访问状态

### 5.5.2 去除 Web 对这些目录的强依赖

```text
/app/uploads
/app/temp
/app/research_reports
/app/data
/app/lib
```

保留短期临时目录：

```text
/tmp/landppt
```

但临时目录内文件不得作为最终下载结果。

### 5.5.3 Session 状态

当前 Session 主体已在数据库，且有 Valkey cache，方向正确。云原生要求：

- 所有 Web Pod 使用相同 `SECRET_KEY`
- Session 记录以数据库为准
- Valkey 仅做缓存，不作为唯一事实来源

---

## 6. Helm Chart 改造方案

## 6.1 目录结构建议

```text
helm/landppt/templates/
  web-deployment.yaml
  worker-deployment.yaml
  service.yaml
  ingress.yaml
  configmap.yaml
  secret.yaml
  migration-job.yaml
  serviceaccount.yaml
  hpa-web.yaml
  hpa-worker.yaml
  pdb-web.yaml
  networkpolicy.yaml
  servicemonitor.yaml
```

## 6.2 values.yaml 结构

```yaml
image:
  repository: bradleylzh/landppt
  tag: "0.3.1"
  pullPolicy: IfNotPresent

web:
  replicaCount: 2
  workers: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "2"
      memory: 4Gi
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70

worker:
  replicaCount: 2
  concurrency: 2
  queues:
    - default
    - export
    - media
  resources:
    requests:
      cpu: "1"
      memory: 2Gi
    limits:
      cpu: "4"
      memory: 8Gi
  autoscaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10

storage:
  backend: s3
  s3:
    endpointUrl: http://minio.minio.svc.cluster.local:9000
    bucket: landppt
    region: us-east-1
    forcePathStyle: true
    existingSecret: landppt-s3

postgresql:
  enabled: false

externalDatabase:
  urlSecretName: landppt-db
  urlSecretKey: DATABASE_URL

valkey:
  enabled: false

externalValkey:
  urlSecretName: landppt-valkey
  urlSecretKey: VALKEY_URL

migration:
  enabled: true
  hook: true

observability:
  serviceMonitor:
    enabled: true
  otel:
    enabled: true
    endpoint: http://otel-collector:4317
```

## 6.3 Web Deployment

- 多副本
- readiness/liveness
- 不挂载业务 PVC
- `/tmp` 使用 emptyDir
- `/dev/shm` 使用 memory emptyDir

```yaml
volumes:
  - name: tmp
    emptyDir: {}
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 4Gi
```

## 6.4 Worker Deployment

- 独立资源限制
- 可绑定 nodeSelector 到高性能节点
- 可区分队列：`default`、`export`、`media`
- 视频导出 Worker 可单独 Deployment

建议拆分：

```text
landppt-worker-default
landppt-worker-export
landppt-worker-media
```

其中 media worker 给更高内存和 CPU。

---

## 7. 数据和文件迁移方案

## 7.1 本地文件迁移到对象存储

### 7.1.1 迁移范围

```text
/app/uploads
/app/temp/images_cache
/app/research_reports
/app/data/artifacts
```

### 7.1.2 迁移脚本

新增：

```text
scripts/migrate_local_files_to_s3.py
```

迁移流程：

1. 扫描本地目录
2. 计算 SHA256
3. 上传到 S3
4. 创建 artifacts 记录
5. 更新相关业务表中的路径字段为 artifact id / storage key
6. 生成迁移报告

### 7.1.3 兼容期

短期保留：

```python
if artifact_id exists:
    read from storage
else:
    fallback to legacy local path
```

兼容期结束后移除本地路径读取。

---

## 8. 配置和 Secret 管理

## 8.1 配置分类

| 类型 | 示例 | 存放位置 |
|---|---|---|
| 非敏感配置 | `LOG_LEVEL`、`WORKERS` | ConfigMap |
| 敏感配置 | `SECRET_KEY`、AI API Key、DB URL | Secret / ExternalSecret |
| 动态业务配置 | 用户模型配置、额度 | PostgreSQL |
| 大型文件配置 | 模板资产、图片 | S3/MinIO |

## 8.2 推荐接入 External Secrets

```text
Vault / AWS Secrets Manager / Aliyun KMS / Kubernetes Secret
        ↓
ExternalSecrets Operator
        ↓
Kubernetes Secret
        ↓
LandPPT Web / Worker
```

---

## 9. 可观测性方案

## 9.1 日志

要求：

- JSON 格式日志
- 包含 `request_id`、`user_id`、`project_id`、`task_id`
- stdout 输出，由集群采集

推荐字段：

```json
{
  "level": "INFO",
  "timestamp": "2026-07-06T00:00:00Z",
  "service": "landppt-web",
  "request_id": "...",
  "user_id": 1,
  "project_id": "...",
  "task_id": "...",
  "message": "export pdf queued"
}
```

## 9.2 指标

新增 `/metrics` Prometheus endpoint。

核心指标：

```text
landppt_http_requests_total
landppt_http_request_duration_seconds
landppt_tasks_total
landppt_task_duration_seconds
landppt_task_failures_total
landppt_queue_depth
landppt_storage_put_bytes_total
landppt_storage_get_bytes_total
landppt_export_duration_seconds
landppt_ai_provider_latency_seconds
landppt_ai_provider_errors_total
```

## 9.3 链路追踪

接入 OpenTelemetry：

- FastAPI middleware
- HTTP client instrumentation
- SQLAlchemy instrumentation
- Redis instrumentation
- 任务执行 trace context 传递

---

## 10. 安全方案

## 10.1 容器安全

- 默认非 root 运行
- root filesystem 只读
- 禁止 privilege escalation
- 镜像漏洞扫描
- 最小化 Linux capability

示例：

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL
```

> 注意：当前 Dockerfile 注释中提到“run as root for compatibility”。云原生改造需要逐步修复文件权限和 Chromium 运行问题，再切换非 root。

非 root 与 `readOnlyRootFilesystem` 改造必须单独验收 Playwright/Chromium 导出链路。PDF、PPTX、HTML、视频相关导出在非 root、只读根文件系统、`/tmp` emptyDir、`/dev/shm` memory emptyDir 下全部通过后，才能在生产默认启用该安全配置。

## 10.2 网络安全

- NetworkPolicy 限制 Web/Worker 只访问必要服务
- PostgreSQL、Valkey、MinIO 不暴露公网
- Ingress 强制 HTTPS
- 管理接口加 admin 权限

## 10.3 文件安全

- 上传文件类型白名单
- 文件大小限制
- 病毒扫描，可选 ClamAV
- 对象存储 key 不暴露真实本地路径
- 下载必须鉴权或使用短期 URL

---

## 11. CI/CD 方案

## 11.1 镜像构建

每次发布生成不可变 tag：

```text
landppt:0.3.1
landppt:git-<sha>
landppt:<branch>-<sha>
```

禁止生产使用：

```text
latest
```

## 11.2 流水线

```text
lint -> test -> build image -> scan image -> push image -> helm lint -> deploy staging -> e2e -> deploy prod
```

## 11.3 GitOps

推荐：

- Argo CD
- Flux

环境目录：

```text
deploy/
  environments/
    dev/values.yaml
    staging/values.yaml
    prod/values.yaml
```

---

## 12. 高可用和伸缩策略

## 12.1 Web HPA

依据：

- CPU
- Memory
- RPS
- P95 latency

初始建议：

```yaml
minReplicas: 2
maxReplicas: 10
targetCPUUtilizationPercentage: 70
```

## 12.2 Worker HPA

依据：

- Redis queue depth
- Running task count
- CPU/Memory

例如：

```text
queue_depth > 20 扩容
queue_depth < 5 缩容
```

可使用 KEDA：

```text
KEDA + Redis Scaler
```

## 12.3 资源隔离

建议拆分 Worker：

| Worker | 任务 | 资源 |
|---|---|---|
| default | 普通 PPT 生成、文本任务 | 中等 CPU/内存 |
| export | PDF/PPTX/HTML 导出 | 高 CPU/内存 |
| media | 音频、视频导出 | 高 CPU/高内存 |

---

## 13. 任务可靠性设计

## 13.1 幂等性

任务必须支持重复执行：

- 使用 `task_id` 作为输出目录
- 写结果前先检查 artifact 是否已存在
- DB 更新使用事务
- 失败重试不产生重复计费或重复文件

## 13.2 重试策略

```text
普通任务：最多 3 次
AI provider timeout：指数退避重试
视频导出：默认不自动重试或最多 1 次
用户取消：不重试
```

## 13.3 死信队列

失败超过最大次数进入：

```text
failed / dead_letter
```

管理员可重新投递。

## 13.4 任务取消

任务表增加：

```sql
cancel_requested BOOLEAN DEFAULT false
```

Worker 在关键步骤检查取消信号。

---

## 14. 需要修改的关键文件清单

| 文件/目录 | 改造内容 |
|---|---|
| `src/landppt/core/config.py` | 增加 Storage、Queue、Observability 配置 |
| `src/landppt/main.py` | 移除核心 `/temp` 静态依赖，增加 metrics middleware |
| `src/landppt/services/background_tasks.py` | 逐步替换为队列任务服务 |
| `src/landppt/services/progress_tracker.py` | 状态统一进入 async_tasks / Redis |
| `src/landppt/web/route_modules/export_routes.py` | 导出任务提交队列，下载使用 artifact |
| `src/landppt/web/route_modules/narration_routes.py` | 音视频任务队列化，对象存储化 |
| `src/landppt/web/route_modules/slide_routes.py` | 重生成任务队列化 |
| `src/landppt/web/route_modules/speech_script_routes.py` | 演讲稿任务队列化 |
| `src/landppt/services/image/cache/image_cache.py` | 图片缓存对象存储化 |
| `src/landppt/database/startup_initialization.py` | 生产禁用启动初始化，改 CLI/Job |
| `helm/landppt/templates/deployment.yaml` | 拆成 web/worker deployment |
| `helm/landppt/values.yaml` | 增加 web/worker/storage/migration 配置 |

---

## 15. 分阶段实施计划

## 阶段 A：基础稳定化，1-2 周

- [ ] 固定镜像 tag
- [ ] 外置 PostgreSQL
- [ ] 外置 Valkey
- [ ] Secret 从 values.yaml 移除
- [ ] 生产关闭 API docs 或加权限
- [ ] 配置资源 requests/limits
- [ ] 增加基础备份策略

交付结果：稳定单副本生产部署。

## 阶段 A2：迁移 Job 化，1 周

- [ ] 新增 `landppt.cli` 迁移入口
- [ ] 新增 `migrate` / `bootstrap-default-templates` / `bootstrap-admin` / `migrate-and-bootstrap` 命令
- [ ] 生产环境设置 `LANDPPT_AUTO_MIGRATE_ON_STARTUP=false`
- [ ] Helm 增加 migration Job，支持 Helm Hook 或 CI/CD 显式执行
- [ ] 验证 Helm upgrade 不触发 Web 多副本并发迁移

交付结果：数据库迁移和初始化从 Web 启动路径中剥离，为后续多副本做好前提准备。

## 阶段 B：Storage 抽象，2-4 周

- [ ] 新增 `ArtifactStorage`
- [ ] 实现 `LocalStorage`
- [ ] 实现 `S3Storage`
- [ ] 新增 `artifacts` 表
- [ ] 改造 PDF/PPTX/HTML 导出
- [ ] 改造讲解音频/视频下载
- [ ] 改造图片缓存
- [ ] 改造 `/temp` 访问

交付结果：Web Pod 不依赖本地业务文件。

## 阶段 C：任务队列，3-6 周

- [ ] 引入 arq 或其他队列
- [ ] 新增 `async_tasks` 表
- [ ] 新增 Worker 入口
- [ ] 迁移 PDF/PPTX/HTML 导出任务
- [ ] 迁移音频/视频任务
- [ ] 评估批量幻灯片、演讲稿、PPT 全量生成是否适合队列化
- [ ] 保留大纲/幻灯片流式生成等实时交互任务在 Web 中执行
- [ ] 增加任务重试、取消、死信

交付结果：文件型长任务从 Web 中剥离，Web 和 Worker 初步解耦。

## 阶段 D：K8s 原生化，2-3 周

- [ ] Helm 拆分 Web/Worker
- [ ] 增加 HPA/KEDA
- [ ] 增加 PDB
- [ ] 增加 NetworkPolicy
- [ ] 增加 ServiceMonitor
- [ ] 增加多环境 values

交付结果：Web 多副本，Worker 可扩缩容。

## 阶段 E：SaaS 强化，按需持续迭代

该阶段仅在正式 SaaS 运营诉求明确后推进，不作为完成基础云原生改造的前置条件。

- [ ] 多租户资源隔离
- [ ] 存储配额
- [ ] 审计日志
- [ ] OpenTelemetry
- [ ] 灾备演练
- [ ] 成本监控

---

## 16. 验收标准

### 16.1 Web 无状态验收

- [ ] Web Pod 删除后用户登录状态不丢失
- [ ] Web Pod 删除后项目列表正常
- [ ] Web Pod 删除后导出结果仍可下载
- [ ] Web 扩容到 2 个副本后上传/下载/导出正常
- [ ] Web Pod 不挂载业务 PVC

### 16.2 任务系统验收

- [ ] Web 重启不影响已提交任务状态
- [ ] Worker 重启后任务可失败重试或恢复
- [ ] 同一项目重复提交任务能正确去重或排队
- [ ] 任务进度跨 Pod 可查询
- [ ] 任务结果从对象存储下载

### 16.3 K8s 验收

- [ ] Helm upgrade 不触发并发迁移
- [ ] Web Deployment 可 RollingUpdate
- [ ] Worker 可独立扩缩容
- [ ] HPA/KEDA 可根据负载扩容
- [ ] 日志、指标、trace 可查询

### 16.4 容器安全验收

- [ ] Web/Worker 可在非 root 用户下启动
- [ ] `readOnlyRootFilesystem` 开启后，应用只写 `/tmp/landppt`、`/dev/shm` 等显式临时目录
- [ ] Playwright/Chromium PDF、PPTX、HTML、视频导出链路在非 root 模式下正常
- [ ] 失败时能清晰区分权限、sandbox、共享内存和业务异常

---

## 17. 风险和规避

| 风险 | 影响 | 规避 |
|---|---|---|
| 文件迁移遗漏 | 历史项目资源丢失 | 兼容本地 path 读取 + 迁移报告 |
| Worker 任务重复执行 | 重复计费/重复文件 | 幂等 key + DB 状态锁 |
| 视频导出资源过高 | OOM/节点压力 | media worker 独立资源和并发限制 |
| S3 网络抖动 | 下载/上传失败 | 重试、断点、超时、失败可重跑 |
| 迁移 Job 失败 | 发布阻塞 | pre-prod 演练 + rollback |
| 非 root Chromium 兼容性 | 导出失败 | 单独验证 Playwright sandbox 配置 |

---

## 18. 推荐最终部署形态

生产环境推荐：

```text
Kubernetes 集群
├── landppt-web x 2+
├── landppt-worker-default x 1+
├── landppt-worker-export x 1+
├── landppt-worker-media x 0-3
├── PostgreSQL：云数据库或高可用集群
├── Valkey/Redis：云 Redis 或高可用集群
├── S3/MinIO：对象存储
├── Ingress Nginx / Gateway API
├── Prometheus + Grafana
├── Loki / ELK
├── OpenTelemetry Collector
└── Argo CD / Flux
```

---

## 19. 最小推荐落地顺序

如果只选最关键的路径，建议按这个顺序：

1. **基础稳定化**：固定镜像 tag、Secret 外置、生产使用外部 PostgreSQL/Valkey。
2. **迁移 Job 化**：新增 CLI/Job，生产关闭 Web 启动迁移。
3. **Storage 抽象 + artifacts 表**：先改导出下载和 `/temp` 访问，图片缓存可后置。
4. **Worker 队列化**：优先迁移 PDF/PPTX/HTML 导出、音频、视频等文件型长任务。
5. **拆 Helm Web/Worker + 多副本**：再引入 HPA/KEDA、ServiceMonitor、NetworkPolicy 等 K8s 能力。

原因：迁移 Job 是多副本前提；文件仍在本地时，即使拆了 Worker 和 K8s 多副本，也会出现下载失败、缓存不一致、任务结果丢失等问题；流式生成任务则应等队列化边界明确后再评估。

---

## 20. 一句话总结

LandPPT 的完全云原生改造核心是：

> **Web 无状态，文件进对象存储，文件型长任务进 Worker，实时流式生成保留清晰边界，状态进 PostgreSQL/Valkey，部署交给 Helm/GitOps，观测交给 Prometheus/OpenTelemetry。**
