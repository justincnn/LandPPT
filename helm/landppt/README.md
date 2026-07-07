# LandPPT Helm Chart

在 Kubernetes 上部署 LandPPT（含可选的内置 PostgreSQL 和 Valkey）。

## 快速开始

```bash
kubectl create secret generic landppt-keys \
  --namespace landppt \
  --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=OPENAI_API_KEY=sk-xxx

helm install landppt ./helm/landppt \
  --namespace landppt --create-namespace \
  --set app.existingSecret=landppt-keys \
  --set postgresql.auth.password=$(openssl rand -hex 16)
```

访问：

```bash
kubectl port-forward -n landppt svc/landppt 8000:8000
# 打开 http://localhost:8000/web
```

## 常用配置

| 参数 | 说明 | 默认值 |
|---|---|---|
| `image.repository` / `image.tag` | 镜像 | `bradleylzh/landppt:0.3.1` |
| `app.workers` | uvicorn worker 数 | `2` |
| `app.env` | 非敏感环境变量（ConfigMap） | 见 values.yaml |
| `app.secrets` | 敏感环境变量（Secret），生产建议使用 `app.existingSecret` | `{}` |
| `app.existingSecret` | 使用已有 Secret（key 即环境变量名） | `""` |
| `migration.enabled` / `migration.hook` | 数据库迁移 Job / Helm Hook | `false` / `false` |
| `storage.backend` | 文件产物存储后端，生产默认使用 MinIO/S3 | `s3` |
| `storage.s3.endpointUrl` / `storage.s3.bucket` | MinIO/S3 endpoint 和 bucket | `http://minio.minio.svc.cluster.local:9000` / `landppt` |
| `worker.enabled` / `worker.replicaCount` | 启用独立任务 Worker 和副本数 | `true` / `1` |
| `persistence.enabled` | 是否挂载旧式业务 PVC；对象存储模式默认关闭 | `false` |
| `LANDPPT_EXPOSE_TEMP_STATIC_FILES` | Helm 默认关闭 `/temp` 本地临时目录暴露 | `false` |
| `web.autoscaling.enabled` / `worker.autoscaling.enabled` | Web / Worker HPA | `false` / `false` |
| `web.pdb.enabled` / `worker.pdb.enabled` | Web / Worker PodDisruptionBudget | `false` / `false` |
| `networkPolicy.enabled` | 生成基础 NetworkPolicy | `false` |
| `observability.serviceMonitor.enabled` | 生成 Prometheus Operator ServiceMonitor | `false` |
| `postgresql.enabled` | 部署内置 PostgreSQL | `true` |
| `externalDatabase.url` | 外部数据库连接串（关闭内置时必填） | `""` |
| `valkey.enabled` | 部署内置 Valkey 缓存 | `true` |
| `externalValkey.url` | 外部 Valkey/Redis URL | `""` |
| `persistence.enabled` | 应用数据持久化（5 个 PVC） | `true` |
| `persistence.storageClass` | 存储类 | 集群默认 |
| `ingress.enabled` | 启用 Ingress | `false` |
| `shmSize` | /dev/shm 大小（Chromium 渲染需要） | `4Gi` |

## 使用外部数据库 / 缓存

```bash
helm install landppt ./helm/landppt \
  --set postgresql.enabled=false \
  --set externalDatabase.url="postgresql://user:pass@pg-host:5432/landppt" \
  --set valkey.enabled=false \
  --set externalValkey.url="valkey://redis-host:6379"
```

## 使用已有 Secret 管理密钥

```bash
kubectl create secret generic landppt-keys \
  --from-literal=SECRET_KEY=... \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=S3_ACCESS_KEY_ID=minio \
  --from-literal=S3_SECRET_ACCESS_KEY=minio-secret

helm install landppt ./helm/landppt --set app.existingSecret=landppt-keys
```

未设置 `app.existingSecret` 时，必须通过 `app.secrets` 显式提供 `SECRET_KEY` 等敏感值；chart 不再提供生产不安全的默认密钥。

## MinIO / S3 对象存储

Chart 默认设置 `storage.backend=s3`，用于将导出结果、音频、视频等产物写入 MinIO/S3 兼容对象存储。非敏感配置在 `storage.s3` 中设置，访问密钥通过 `app.existingSecret` 提供：

```yaml
storage:
  backend: s3
  s3:
    endpointUrl: http://minio.minio.svc.cluster.local:9000
    bucket: landppt
    region: us-east-1
    forcePathStyle: true
    existingSecret: landppt-s3
minio:
  enabled: false
```

Secret 中需要包含 `S3_ACCESS_KEY_ID` 和 `S3_SECRET_ACCESS_KEY`。本地开发可设置 `storage.backend=local`。

## 数据库迁移 Job

Chart 默认设置 `migration.enabled=false`，避免使用内置 PostgreSQL 时 pre-install Hook 早于数据库 StatefulSet 创建，也避免普通 Job 在 Helm upgrade 时遇到不可变字段。开启后 Job 执行命令为：

```bash
python -m landppt.cli migrate-and-bootstrap
```

Web Pod 默认设置 `LANDPPT_AUTO_MIGRATE_ON_STARTUP=false`，避免多副本启动时并发迁移。生产环境使用外部 PostgreSQL 时，可设置 `migration.enabled=true` 和 `migration.hook=true` 让 Helm 在 install/upgrade 前运行迁移；使用内置 PostgreSQL 时建议保持 `migration.hook=false`，待数据库就绪后由 CI/CD 或运维显式执行 Job。

## 启用 Ingress

```yaml
# my-values.yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: landppt.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: landppt-tls
      hosts:
        - landppt.example.com
```

## 说明

- 应用 PVC 均为 `ReadWriteOnce`，Deployment 使用 `Recreate` 策略，`replicaCount` 建议保持 1。多副本需要 RWX 存储并自行调整。
- Chromium 导出 PPT 需要较大共享内存，chart 通过内存 `emptyDir` 挂载 `/dev/shm`（对应 docker-compose 的 `shm_size: 4gb`），该内存计入容器 memory limit。
- 健康检查使用应用的 `/health` 端点。
