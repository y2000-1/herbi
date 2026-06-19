# HerbiEstim 华为云部署指南

## 目录

- [架构概览](#架构概览)
- [前置准备](#前置准备)
- [第一步：购买并配置华为云 ECS](#第一步购买并配置华为云-ecs)
- [第二步：服务器环境初始化](#第二步服务器环境初始化)
- [第三步：Docker 部署](#第三步docker-部署)
- [第四步：配置 Nginx 反向代理](#第四步配置-nginx-反向代理)（无域名 / 有域名均可）
- [第五步：验证服务](#第五步验证服务)
- [第六步：鸿蒙应用对接](#第六步鸿蒙应用对接)
- [运维与监控](#运维与监控)
- [环境变量参考](#环境变量参考)
- [常见问题](#常见问题)

---

## 架构概览

```
┌──────────────┐       HTTPS        ┌──────────────────────────────────┐
│  鸿蒙应用     │  ─────────────►   │  华为云 ECS (GPU/CPU)            │
│  (ArkTS)     │  ◄─────────────   │  ┌────────────────────────────┐  │
│              │    JSON + Base64   │  │  Nginx (反向代理 + SSL)     │  │
└──────────────┘                    │  │       ↓ :8000              │  │
                                    │  │  Docker Container          │  │
                                    │  │  ┌──────────────────────┐  │  │
                                    │  │  │  FastAPI (uvicorn)   │  │  │
                                    │  │  │  ├── /api/v1/health  │  │  │
                                    │  │  │  └── /api/v1/analyze │  │  │
                                    │  │  │       ↓              │  │  │
                                    │  │  │  HerbiEstimPipeline  │  │  │
                                    │  │  │  ├── split (OpenCV)  │  │  │
                                    │  │  │  ├── pix2pix (UNet)  │  │  │
                                    │  │  │  └── calculation     │  │  │
                                    │  │  └──────────────────────┘  │  │
                                    │  └────────────────────────────┘  │
                                    └──────────────────────────────────┘
```

---

## 前置准备

### 所需账号

- [华为云账号](https://www.huaweicloud.com/)（需完成实名认证）
- 域名（可选，用于 HTTPS 访问）

### 本地文件确认

部署前确保项目目录包含以下文件：

```
HerbiEstim-main/
├── api/
│   ├── __init__.py
│   ├── app.py            # FastAPI 主应用
│   ├── config.py          # 环境变量配置
│   ├── middleware.py       # 鉴权 + 限流
│   ├── pipeline.py        # 推理管线
│   └── schemas.py         # 数据模型
├── pix2pix/               # GAN 模型代码
├── utils/                 # 工具模块
├── model_saved/
│   └── universal/
│       ├── latest_net_G.pth   # pix2pix 生成器权重 (~54MB)
│       └── latest_net_D.pth   # 判别器（推理不需要）
├── split.py
├── modelpredict.py
├── calculation.py
├── Dockerfile
├── docker-compose.yml
├── requirements-api.txt
└── ...
```

### 选择实例规格

| 场景 | 推荐规格 | 月费参考 |
|------|---------|---------|
| **仅 OpenCV + pix2pix（推荐）** | ECS s6.large.2（2vCPU, 4GB） | ~￥150/月 |
| OpenCV + pix2pix（高并发） | ECS c6.xlarge.2（4vCPU, 8GB） | ~￥300/月 |
| 含 SAM 模式 | ECS p2s.xlarge（GPU V100 16GB） | ~￥3000+/月 |

> **建议**：初期使用 CPU 实例（仅 pix2pix），单次推理约 3-5 秒，足够满足一般使用需求。

---

## 第一步：购买并配置华为云 ECS

### 1.1 创建 ECS 实例

1. 登录 [华为云控制台](https://console.huaweicloud.com/)
2. 导航到 **弹性云服务器 ECS** → **购买弹性云服务器**
3. 配置参数：

| 配置项 | 推荐值 |
|--------|-------|
| 区域 | 选择离用户最近的区域（如 华北-北京四） |
| 可用区 | 随机分配 |
| 规格 | 通用计算型 s6.large.2（2vCPU, 4GB RAM） |
| 镜像 | Ubuntu 22.04 64bit |
| 系统盘 | 高IO 50GB |
| 数据盘 | 无（模型文件打包在 Docker 镜像中） |
| 弹性公网IP | 立即购买，按流量计费，带宽 5Mbps |
| 安全组 | 放通 **22(SSH)**, **80(HTTP)**, **443(HTTPS)**, **8000(API)** |
| 登录方式 | 密钥对（推荐）或密码 |

4. 确认订单并购买

### 1.2 配置安全组

在 **网络控制台** → **安全组** 中，添加入站规则：

| 协议 | 端口 | 源地址 | 说明 |
|------|------|--------|------|
| TCP | 22 | 0.0.0.0/0 | SSH 登录（建议限制为你的 IP） |
| TCP | 80 | 0.0.0.0/0 | HTTP |
| TCP | 443 | 0.0.0.0/0 | HTTPS |
| TCP | 8000 | 127.0.0.1/32 | API（仅 Nginx 内部转发） |

### 1.3 绑定弹性公网 IP

记录分配的公网 IP 地址，后续用于 SSH 连接和域名解析。

---

## 第二步：服务器环境初始化

### 2.1 SSH 连接到服务器

```bash
# Windows PowerShell 或 cmd
ssh -i your-key.pem root@<ECS公网IP>
```

### 2.2 安装 Docker

```bash
# 更新系统
apt-get update && apt-get upgrade -y

# 安装 Docker
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 验证安装
docker --version
docker compose version
```

> 如果使用华为云镜像加速器，可配置 Docker Hub mirror：
> ```bash
> mkdir -p /etc/docker
> cat > /etc/docker/daemon.json << 'EOF'
> {
>   "registry-mirrors": ["https://<你的华为云镜像加速地址>.mirror.swr.myhuaweicloud.com"]
> }
> EOF
> systemctl restart docker
> ```

### 2.3 安装 Nginx

```bash
apt-get install -y nginx
systemctl enable nginx
```

### 2.4（可选）安装 NVIDIA Docker（仅 GPU 实例）

```bash
# 安装 NVIDIA Container Toolkit
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
apt-get install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

# 验证 GPU
docker run --rm --gpus all nvidia/cuda:11.7.1-base-ubuntu22.04 nvidia-smi
```

---

## 第三步：Docker 部署

### 3.1 上传项目代码到服务器

**方式 A：Git 拉取（推荐）**

```bash
cd /opt
git clone <你的仓库地址> herbiestim
cd herbiestim
```

**方式 B：SCP 上传**

```bash
# 在本地 Windows 执行
scp -i your-key.pem -r D:\MyProject\Python\HerbiEstim-main root@<ECS公网IP>:/opt/herbiestim
```

> **注意**：确保 `model_saved/universal/latest_net_G.pth` 文件已上传。它约 54MB，是推理必需的模型权重。

### 3.2 配置环境变量

```bash
cd /opt/herbiestim

# 创建 .env 文件
cat > .env << 'EOF'
# === 模型配置 ===
HERBI_MODEL_NAME=universal
HERBI_CHECKPOINTS_DIR=/app/model_saved
HERBI_GPU_IDS=

# === SAM 配置（CPU 实例请保持 false）===
HERBI_ENABLE_SAM=false
HERBI_SAM_DEVICE=cpu

# === API 安全 ===
HERBI_API_KEY=your-secret-api-key-here-change-this
HERBI_CORS_ORIGINS=*
HERBI_RATE_LIMIT_PER_MINUTE=30
HERBI_MAX_UPLOAD_SIZE_MB=20
HERBI_DEFAULT_DPI=300

# === Docker Compose ===
API_PORT=8000
EOF
```

> **重要**：将 `HERBI_API_KEY` 修改为一个安全的随机字符串。鸿蒙端调用时需要在请求头中携带此 Key。
> 
> 生成随机 Key：`openssl rand -hex 32`

### 3.3 构建 Docker 镜像

```bash
cd /opt/herbiestim

# CPU 模式（默认，推荐。基础镜像为 python:3.10-slim，体积更小）
docker build -t herbiestim-api:latest .

# GPU 模式（安装 CUDA 版 PyTorch，镜像更大）
# docker build --build-arg USE_GPU=true -t herbiestim-api:gpu .
```

构建过程约 5-10 分钟（取决于网络速度）。CPU 模式镜像约 2-3 GB，GPU 模式约 5-6 GB。

> **网络问题？** 如果构建过程中 pip 下载超时，参见 [Q1: 构建镜像时拉取基础镜像超时 / 下载 PyTorch 很慢](#q1-构建镜像时拉取基础镜像超时--下载-pytorch-很慢)。

### 3.4 启动服务

**CPU 模式：**

```bash
docker compose up -d
```

**GPU 模式：**

```bash
# 修改 .env
echo "HERBI_GPU_IDS=0" >> .env

docker compose --profile gpu up -d
```

### 3.5 验证容器运行

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f --tail=50

# 预期日志输出：
# HerbiEstim API starting up...
#   Model: universal
#   pix2pix model loaded.
# Pipeline ready. Accepting requests.
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 3.6 测试 API

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 预期返回：
# {"status":"healthy","pix2pix_loaded":true,"sam_loaded":false,"gpu_available":false}
```

---

## 第四步：配置 Nginx 反向代理

> **没有域名？** 完全没问题！直接使用 ECS 弹性公网 IP 即可。下面提供两种方案，按需选择。

### 方案 A：无域名，直接用公网 IP（推荐新手）

这是最简单的方式，无需购买域名，直接通过 `http://<ECS公网IP>` 访问服务。

#### 4.1A 配置 Nginx 反向代理（IP 模式）

```bash
# 将 <ECS公网IP> 替换为你实际的公网 IP 地址
cat > /etc/nginx/sites-available/herbiestim << 'EOF'
server {
    listen 80;
    server_name _;  # 匹配所有请求（无域名时使用）

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时设置（推理可能需要较长时间）
        proxy_connect_timeout 60s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
EOF

# 启用站点
ln -sf /etc/nginx/sites-available/herbiestim /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 检查配置并重启
nginx -t
systemctl reload nginx
```

#### 4.2A 验证 HTTP 访问

```bash
# 服务器本地测试
curl http://localhost/api/v1/health

# 从外部（本地电脑）测试，替换为实际 IP
curl http://<ECS公网IP>/api/v1/health
```

#### 4.3A（可选）为 IP 配置自签名 HTTPS

> Let's Encrypt **不支持**为纯 IP 签发证书。如果鸿蒙端要求 HTTPS，可以使用自签名证书。
> 注意：自签名证书会触发浏览器安全警告，客户端代码需要配置信任或跳过证书验证。

```bash
# 生成自签名证书（有效期 10 年），将 <ECS公网IP> 替换为实际 IP
mkdir -p /etc/nginx/ssl

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/selfsigned.key \
  -out /etc/nginx/ssl/selfsigned.crt \
  -subj "/CN=<ECS公网IP>" \
  -addext "subjectAltName=IP:<ECS公网IP>"

# 更新 Nginx 配置，同时支持 HTTP 和 HTTPS
cat > /etc/nginx/sites-available/herbiestim << 'EOF'
server {
    listen 80;
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
EOF

nginx -t
systemctl reload nginx
```

验证：

```bash
# HTTP 访问
curl http://<ECS公网IP>/api/v1/health

# HTTPS 访问（-k 跳过自签名证书验证）
curl -k https://<ECS公网IP>/api/v1/health
```

> **鸿蒙端对接注意**：如果使用自签名 HTTPS，ArkTS 中的 HTTP 请求需要配置 `caPath` 或在系统设置中信任该证书。  
> 如果仅内网/测试使用，**直接用 HTTP 即可**，更简单。

---

### 方案 B：有域名，配置正式 HTTPS

如果你已有域名，可以使用 Let's Encrypt 获取免费可信证书。

#### 4.1B 配置 Nginx 反向代理（域名模式）

```bash
cat > /etc/nginx/sites-available/herbiestim << 'EOF'
server {
    listen 80;
    server_name your-domain.com;  # 替换为你的域名

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 60s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/herbiestim /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

#### 4.2B 配置域名解析

1. 在域名注册商处添加 A 记录，指向 ECS 公网 IP
2. 在华为云 [DNS 解析](https://console.huaweicloud.com/dns/) 中添加记录（如果域名在华为云）

| 记录类型 | 主机记录 | 记录值 |
|---------|---------|-------|
| A | api（或 @） | `<ECS公网IP>` |

#### 4.3B 申请 SSL 证书（HTTPS）

**方式一：Let's Encrypt 免费证书（推荐）**

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
systemctl enable certbot.timer
```

**方式二：华为云 SSL 证书**

1. 在 [华为云 SSL 证书管理](https://console.huaweicloud.com/ccm/) 购买或申请免费证书
2. 下载 Nginx 格式的证书文件
3. 上传至 `/etc/nginx/ssl/` 并配置 Nginx

#### 4.4B 验证 HTTPS

```bash
curl https://your-domain.com/api/v1/health
```

---

## 第五步：验证服务

### 5.1 完整推理测试

```bash
# 从服务器本地测试（将一张叶片图片上传）
# 无域名方案：使用 http://<ECS公网IP>
curl -X POST http://<ECS公网IP>/api/v1/analyze \
  -H "X-API-Key: your-secret-api-key-here-change-this" \
  -F "image=@/opt/herbiestim/imgs_raw/s1.png" \
  -F "dpi=300" \
  -F "return_images=false"

# 有域名方案：使用 https://your-domain.com
# curl -X POST https://your-domain.com/api/v1/analyze \
#   -H "X-API-Key: your-secret-api-key-here-change-this" \
#   -F "image=@/opt/herbiestim/imgs_raw/s1.png" \
#   -F "dpi=300" \
#   -F "return_images=false"
```

预期返回：

```json
{
  "leaves": [
    {
      "leaf_id": 0,
      "leaf_area_cm2": 19.221,
      "intact_area_cm2": 26.908,
      "damage_pct": 0.286,
      "standardized_image": null,
      "reconstructed_image": null
    }
  ],
  "summary": {
    "num_leaves": 1,
    "total_leaf_area_cm2": 19.221,
    "total_intact_area_cm2": 26.908,
    "avg_damage_pct": 0.286
  }
}
```

### 5.2 使用项目自带的测试脚本

```bash
# 修改 test_api.py 中的 base_url 为实际地址后运行
cd /opt/herbiestim
python test_api.py
```

### 5.3 交互式 API 文档

浏览器打开 `http://<ECS公网IP>/docs`（无域名）或 `https://your-domain.com/docs`（有域名），即可看到 Swagger UI 交互界面，支持直接上传图片测试。

---

## 第六步：鸿蒙应用对接

### 6.1 ArkTS 调用示例

```typescript
// services/HerbiEstimService.ets

import http from '@ohos.net.http';
import image from '@ohos.multimedia.image';

// 无域名方案：直接用公网 IP
const API_BASE = 'http://<ECS公网IP>';
// 有域名方案：
// const API_BASE = 'https://your-domain.com';
const API_KEY = 'your-secret-api-key-here-change-this';

interface LeafResult {
  leaf_id: number;
  leaf_area_cm2: number | null;
  intact_area_cm2: number | null;
  damage_pct: number;
  standardized_image: string | null;
  reconstructed_image: string | null;
}

interface AnalysisSummary {
  num_leaves: number;
  total_leaf_area_cm2: number | null;
  total_intact_area_cm2: number | null;
  avg_damage_pct: number;
}

interface AnalyzeResponse {
  leaves: LeafResult[];
  summary: AnalysisSummary;
}

/**
 * 分析叶片损伤
 * @param imageUri 图片文件 URI（来自相册或拍照）
 * @param dpi 图片 DPI（扫描图默认 300）
 * @returns 分析结果
 */
export async function analyzeLeaf(
  imageUri: string,
  dpi: number = 300
): Promise<AnalyzeResponse> {

  let httpRequest = http.createHttp();

  // 读取图片文件为 ArrayBuffer
  // （实际实现需使用 @ohos.file.fs 读取文件）

  let response = await httpRequest.request(
    `${API_BASE}/api/v1/analyze`,
    {
      method: http.RequestMethod.POST,
      header: {
        'X-API-Key': API_KEY,
        'Content-Type': 'multipart/form-data',
      },
      multiFormDataList: [
        {
          name: 'image',
          contentType: 'image/jpeg',
          remoteFileName: 'leaf.jpg',
          filePath: imageUri,
        },
        {
          name: 'dpi',
          contentType: 'text/plain',
          data: dpi.toString(),
        },
        {
          name: 'return_images',
          contentType: 'text/plain',
          data: 'true',
        },
        {
          name: 'use_sam',
          contentType: 'text/plain',
          data: 'false',
        }
      ],
      connectTimeout: 30000,
      readTimeout: 120000,  // 推理可能较慢
    }
  );

  if (response.responseCode !== 200) {
    throw new Error(`API error: ${response.responseCode}`);
  }

  return JSON.parse(response.result as string) as AnalyzeResponse;
}
```

### 6.2 鸿蒙端展示结果

```typescript
// pages/LeafAnalysis.ets

@Entry
@Component
struct LeafAnalysisPage {
  @State result: AnalyzeResponse | null = null;
  @State loading: boolean = false;

  build() {
    Column() {
      if (this.loading) {
        LoadingProgress()
        Text('正在分析叶片损伤...')
      }

      if (this.result) {
        Text(`检测到 ${this.result.summary.num_leaves} 片叶子`)
          .fontSize(18)
          .fontWeight(FontWeight.Bold)

        Text(`平均损伤率: ${(this.result.summary.avg_damage_pct * 100).toFixed(1)}%`)
          .fontSize(24)
          .fontColor(Color.Red)

        ForEach(this.result.leaves, (leaf: LeafResult) => {
          Row() {
            Text(`叶片 ${leaf.leaf_id}`)
            Text(`${(leaf.damage_pct * 100).toFixed(1)}%`)
          }
          .justifyContent(FlexAlign.SpaceBetween)
          .width('100%')
          .padding(8)
        })

        // 展示重建图片（Base64 解码）
        if (this.result.leaves[0]?.reconstructed_image) {
          Image(`data:image/png;base64,${this.result.leaves[0].reconstructed_image}`)
            .width(256)
            .height(256)
        }
      }
    }
    .padding(16)
  }
}
```

---

## 运维与监控

### 服务管理命令

```bash
# 查看服务状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 更新代码后重新部署
git pull
docker build -t herbiestim-api:latest .
docker compose down
docker compose up -d
```

### 设置开机自启

Docker Compose 中已配置 `restart: unless-stopped`，ECS 重启后容器会自动启动。确保 Docker 服务自启：

```bash
systemctl enable docker
```

### 日志管理

```bash
# 查看最近 100 行日志
docker compose logs --tail=100

# 导出日志
docker compose logs > /var/log/herbiestim.log
```

### 磁盘监控

```bash
# 查看 Docker 镜像/容器占用
docker system df

# 清理无用镜像
docker system prune -f
```

---

## 环境变量参考

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `HERBI_MODEL_NAME` | `universal` | 模型名称（对应 model_saved/ 下的子目录） |
| `HERBI_CHECKPOINTS_DIR` | `/app/model_saved` | 模型权重目录（容器内路径） |
| `HERBI_GPU_IDS` | （空 = CPU） | GPU 设备 ID，如 `0` |
| `HERBI_ENABLE_SAM` | `false` | 是否启加载 SAM 模型 |
| `HERBI_SAM_DEVICE` | `cuda` | SAM 推理设备 |
| `HERBI_SAM_BOX_THRESHOLD` | `0.3` | GroundingDINO 检测阈值 |
| `HERBI_SAM_TEXT_THRESHOLD` | `0.25` | GroundingDINO 文本匹配阈值 |
| `HERBI_API_KEY` | （空 = 无鉴权） | API 访问密钥 |
| `HERBI_CORS_ORIGINS` | `*` | 允许的跨域来源（逗号分隔） |
| `HERBI_RATE_LIMIT_PER_MINUTE` | `30` | 每 IP 每分钟最大请求数 |
| `HERBI_MAX_UPLOAD_SIZE_MB` | `20` | 最大上传文件大小 (MB) |
| `HERBI_DEFAULT_DPI` | `300` | 默认图像 DPI |

---

## 常见问题

### Q1: 构建镜像时拉取基础镜像超时 / 下载 PyTorch 很慢

**现象 A：`docker build` 报 `dial tcp ... i/o timeout`（无法拉取 `pytorch/pytorch` 基础镜像）**

国内 ECS 直连 Docker Hub 经常超时。**最新 Dockerfile 已切换为 `python:3.10-slim` 基础镜像并内置华为云 pip 镜像源**，无需再拉取巨大的 PyTorch Docker 镜像。直接构建即可：

```bash
# CPU 模式（默认，推荐）
docker build -t herbiestim-api:latest .

# GPU 模式
docker build --build-arg USE_GPU=true -t herbiestim-api:gpu .
```

如果连 `python:3.10-slim` 也拉不动，配置 Docker Hub 镜像加速器：

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}
EOF
systemctl restart docker
```

> 华为云用户也可使用华为云 SWR 提供的 Docker Hub 加速地址（需在 SWR 控制台获取）。

**现象 B：pip 安装 PyTorch / 其他依赖很慢**

Dockerfile 默认使用华为云 pip 镜像源。如需切换为其他源，构建时传入参数：

```bash
# 使用清华源
docker build \
  --build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
  --build-arg PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
  -t herbiestim-api:latest .
```

在 ECS 上直接使用 pip 时也可配置全局镜像源：

```bash
mkdir -p ~/.pip
cat > ~/.pip/pip.conf << 'EOF'
[global]
index-url = https://repo.huaweicloud.com/repository/pypi/simple
trusted-host = repo.huaweicloud.com
EOF
```

### Q2: 容器启动后 health 接口返回 `degraded`

检查模型文件是否完整：

```bash
docker exec herbiestim-api ls -la /app/model_saved/universal/
# 应包含 latest_net_G.pth（约 54MB）
```

### Q3: 推理超时

CPU 模式下单张图片推理约 3-5 秒。如果图片较大（含多片叶子），时间会更长。可在 Nginx 中调大 `proxy_read_timeout`。

### Q4: 如何启用 SAM 模式

1. 购买 GPU 实例（推荐 V100 16GB）
2. 安装 NVIDIA Container Toolkit（见第二步）
3. 下载 SAM 权重：
   ```bash
   cd /opt/herbiestim/model_saved
   wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth
   ```
4. 修改 `.env`：
   ```
   HERBI_ENABLE_SAM=true
   HERBI_GPU_IDS=0
   ```
5. 重新启动：`docker compose --profile gpu up -d`

### Q5: 如何更新模型

```bash
# 上传新的模型权重到服务器
scp latest_net_G.pth root@<IP>:/opt/herbiestim/model_saved/universal/

# 重启容器使其重新加载
docker compose restart
```
