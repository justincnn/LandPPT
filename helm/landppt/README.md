# LandPPT Helm Chart

在 Kubernetes 上部署 LandPPT（含可选的内置 PostgreSQL 和 Valkey）。

## 快速开始

```bash
helm install landppt ./helm/landppt \
  --namespace landppt --create-namespace \
  --set app.secrets.SECRET_KEY=$(openssl rand -hex 32) \
  --set app.secrets.OPENAI_API_KEY=sk-xxx \
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
| `image.repository` / `image.tag` | 镜像 | `bradleylzh/landppt:latest` |
| `app.workers` | uvicorn worker 数 | `2` |
| `app.env` | 非敏感环境变量（ConfigMap） | 见 values.yaml |
| `app.secrets` | 敏感环境变量（Secret），如 API Key | `SECRET_KEY` |
| `app.existingSecret` | 使用已有 Secret（key 即环境变量名） | `""` |
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
  --from-literal=OPENAI_API_KEY=sk-...

helm install landppt ./helm/landppt --set app.existingSecret=landppt-keys
```

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
