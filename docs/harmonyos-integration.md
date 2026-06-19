# HerbiEstim 鸿蒙端 API 对接文档

> **版本**: 1.0.0  
> **最后更新**: 2026-02-12  
> **基础地址**: `http://<服务器公网IP>` 或 `https://<你的域名>`

---

## 目录

- [概览](#概览)
- [接入准备](#接入准备)
- [接口说明](#接口说明)
  - [1. 健康检查](#1-健康检查)
  - [2. 叶片损伤分析](#2-叶片损伤分析)
- [数据模型定义](#数据模型定义)
- [鸿蒙端完整代码实现](#鸿蒙端完整代码实现)
  - [网络服务封装](#网络服务封装)
  - [页面调用示例](#页面调用示例)
- [错误处理](#错误处理)
- [常见问题](#常见问题)
- [附录：cURL 调试命令](#附录curl-调试命令)

---

## 概览

HerbiEstim API 是一个基于 pix2pix GAN 的叶片虫害损伤分析服务。鸿蒙端通过 HTTP/HTTPS 上传叶片图片，服务端返回每片叶子的面积与损伤率等信息。

**调用流程：**

```
鸿蒙应用                                 服务端
  │                                        │
  │  1. POST /api/v1/analyze               │
  │     (multipart/form-data: 图片+参数)    │
  │  ────────────────────────────────────►  │
  │                                        │  ── 图像分割
  │                                        │  ── pix2pix 重建
  │                                        │  ── 损伤计算
  │  2. JSON 响应                           │
  │  ◄────────────────────────────────────  │
  │     (损伤率、面积、可选 Base64 图片)      │
  │                                        │
```

---

## 接入准备

### 1. 获取服务地址

向服务端部署人员获取：

| 信息 | 示例 | 说明 |
|------|------|------|
| **API 地址** | `http://123.45.67.89` 或 `https://api.example.com` | 服务器公网 IP 或绑定的域名 |
| **API 密钥** | `a3f8c9d1e2b4...` | 请求头中携带的鉴权密钥 |

### 2. 配置鸿蒙权限

在 `module.json5` 中声明网络权限：

```json5
{
  "module": {
    "requestPermissions": [
      {
        "name": "ohos.permission.INTERNET"
      }
    ]
  }
}
```

### 3. 注意事项

- **图片格式**：支持 JPEG、PNG、TIFF、BMP、WebP
- **图片大小限制**：最大 **20 MB**
- **请求频率限制**：默认每 IP 每分钟 **30 次**
- **超时建议**：连接超时 30s，读取超时 **120s**（CPU 推理可能需要 3-5 秒）
- 如使用自签名 HTTPS 证书，需在鸿蒙端配置证书信任（见 [常见问题](#q4-使用自签名-https-证书时请求失败)）

---

## 接口说明

### 1. 健康检查

用于确认服务是否正常运行。**无需鉴权**。

```
GET /api/v1/health
```

#### 响应示例

```json
{
  "status": "healthy",
  "pix2pix_loaded": true,
  "sam_loaded": false,
  "gpu_available": false
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `string` | `"healthy"` 表示服务正常；`"degraded"` 表示模型未加载 |
| `pix2pix_loaded` | `boolean` | pix2pix 模型是否已加载（必须为 `true` 才能推理） |
| `sam_loaded` | `boolean` | SAM 分割模型是否已加载（可选功能） |
| `gpu_available` | `boolean` | 服务端是否有 GPU 可用 |

> **建议**：应用启动时先调用此接口确认服务可用，再展示分析入口。如 `status` 非 `"healthy"`，提示用户稍后重试。

---

### 2. 叶片损伤分析

上传一张叶片图片，返回每片叶子的损伤分析结果。**需要鉴权**。

```
POST /api/v1/analyze
Content-Type: multipart/form-data
X-API-Key: <你的API密钥>
```

#### 请求参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| `image` | `file` | **是** | — | 叶片图片文件（jpg/png/tiff/bmp/webp） |
| `dpi` | `int` | 否 | `300` | 图像 DPI，用于计算真实面积 (cm²)。范围 72-2400 |
| `is_scanned` | `bool` | 否 | `true` | 图片是否来自扫描仪。`true` 时根据 DPI 计算物理面积，`false` 时面积字段返回 `null` |
| `use_sam` | `bool` | 否 | `false` | 是否使用 SAM 模型进行分割（需服务端开启 SAM 且有 GPU） |
| `return_images` | `bool` | 否 | `true` | 是否在响应中返回 Base64 编码的图片。设为 `false` 可显著减小响应体积 |

#### 成功响应 (200)

```json
{
  "leaves": [
    {
      "leaf_id": 0,
      "leaf_area_cm2": 19.221,
      "intact_area_cm2": 26.908,
      "damage_pct": 0.286,
      "standardized_image": "iVBORw0KGgo...",
      "reconstructed_image": "iVBORw0KGgo..."
    },
    {
      "leaf_id": 1,
      "leaf_area_cm2": 15.102,
      "intact_area_cm2": 18.637,
      "damage_pct": 0.190,
      "standardized_image": "iVBORw0KGgo...",
      "reconstructed_image": "iVBORw0KGgo..."
    }
  ],
  "summary": {
    "num_leaves": 2,
    "total_leaf_area_cm2": 34.323,
    "total_intact_area_cm2": 45.545,
    "avg_damage_pct": 0.238
  }
}
```

#### 响应字段详解

**`leaves` 数组 — 每片叶子的分析结果：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `leaf_id` | `int` | 叶片编号，从 0 开始 |
| `leaf_area_cm2` | `float \| null` | 实际叶片面积 (cm²)。`is_scanned=false` 时为 `null` |
| `intact_area_cm2` | `float \| null` | 重建后的完整叶片面积 (cm²)。`is_scanned=false` 时为 `null` |
| `damage_pct` | `float` | 损伤百分比，范围 `0.0`~`1.0`（例如 `0.286` 表示 28.6%） |
| `standardized_image` | `string \| null` | 标准化叶片图 (Base64 PNG)。`return_images=false` 时为 `null` |
| `reconstructed_image` | `string \| null` | GAN 重建的完整叶片图 (Base64 PNG)。`return_images=false` 时为 `null` |

**`summary` 对象 — 汇总统计：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `num_leaves` | `int` | 检测到的叶片总数 |
| `total_leaf_area_cm2` | `float \| null` | 所有叶片面积之和 |
| `total_intact_area_cm2` | `float \| null` | 所有重建完整面积之和 |
| `avg_damage_pct` | `float` | 所有叶片的平均损伤率 |

---

## 数据模型定义

在鸿蒙端定义以下 TypeScript 接口：

```typescript
// models/HerbiEstimTypes.ets

/** 单片叶子分析结果 */
export interface LeafResult {
  leaf_id: number;
  leaf_area_cm2: number | null;
  intact_area_cm2: number | null;
  damage_pct: number;
  standardized_image: string | null;
  reconstructed_image: string | null;
}

/** 汇总统计 */
export interface AnalysisSummary {
  num_leaves: number;
  total_leaf_area_cm2: number | null;
  total_intact_area_cm2: number | null;
  avg_damage_pct: number;
}

/** 分析接口响应 */
export interface AnalyzeResponse {
  leaves: LeafResult[];
  summary: AnalysisSummary;
}

/** 健康检查响应 */
export interface HealthResponse {
  status: string;
  pix2pix_loaded: boolean;
  sam_loaded: boolean;
  gpu_available: boolean;
}

/** 错误响应 */
export interface ErrorResponse {
  error: string;
  detail: string;
}
```

---

## 鸿蒙端完整代码实现

### 网络服务封装

```typescript
// services/HerbiEstimService.ets

import http from '@ohos.net.http';
import {
  AnalyzeResponse,
  HealthResponse,
  ErrorResponse,
} from '../models/HerbiEstimTypes';

/** API 配置 — 根据实际部署修改 */
const API_BASE = 'http://<服务器公网IP>';  // 或 'https://<你的域名>'
const API_KEY  = '<你的API密钥>';

/**
 * 健康检查 — 确认服务是否可用
 */
export async function checkHealth(): Promise<HealthResponse> {
  const httpRequest = http.createHttp();
  try {
    const response = await httpRequest.request(
      `${API_BASE}/api/v1/health`,
      {
        method: http.RequestMethod.GET,
        connectTimeout: 10000,
        readTimeout: 10000,
      }
    );

    if (response.responseCode !== 200) {
      throw new Error(`Health check failed: HTTP ${response.responseCode}`);
    }

    return JSON.parse(response.result as string) as HealthResponse;
  } finally {
    httpRequest.destroy();
  }
}

/**
 * 分析叶片损伤
 *
 * @param imageUri   - 图片文件路径（来自相册选择或拍照保存后的沙箱路径）
 * @param dpi        - 图片 DPI（扫描图默认 300，手机拍照可填 0 并将 isScanned 设为 false）
 * @param isScanned  - 是否为扫描仪图片（影响是否计算物理面积）
 * @param returnImages - 是否返回 Base64 图片（用于 UI 展示重建结果）
 * @param useSam     - 是否使用 SAM 分割（需服务端支持，一般填 false）
 * @returns 分析结果
 */
export async function analyzeLeaf(
  imageUri: string,
  dpi: number = 300,
  isScanned: boolean = true,
  returnImages: boolean = true,
  useSam: boolean = false,
): Promise<AnalyzeResponse> {

  const httpRequest = http.createHttp();
  try {
    const response = await httpRequest.request(
      `${API_BASE}/api/v1/analyze`,
      {
        method: http.RequestMethod.POST,
        header: {
          'X-API-Key': API_KEY,
        },
        multiFormDataList: [
          {
            name: 'image',
            contentType: 'image/jpeg',
            remoteFileName: 'leaf.jpg',
            filePath: imageUri,         // 沙箱内图片文件路径
          },
          {
            name: 'dpi',
            contentType: 'text/plain',
            data: dpi.toString(),
          },
          {
            name: 'is_scanned',
            contentType: 'text/plain',
            data: isScanned.toString(),
          },
          {
            name: 'return_images',
            contentType: 'text/plain',
            data: returnImages.toString(),
          },
          {
            name: 'use_sam',
            contentType: 'text/plain',
            data: useSam.toString(),
          },
        ],
        connectTimeout: 30000,
        readTimeout: 120000,  // 推理可能耗时较长
      }
    );

    // 处理 HTTP 错误
    if (response.responseCode !== 200) {
      let errMsg = `HTTP ${response.responseCode}`;
      try {
        const err = JSON.parse(response.result as string) as ErrorResponse;
        errMsg = err.detail || errMsg;
      } catch (_) {}
      throw new Error(errMsg);
    }

    return JSON.parse(response.result as string) as AnalyzeResponse;
  } finally {
    httpRequest.destroy();
  }
}
```

### 页面调用示例

```typescript
// pages/LeafAnalysisPage.ets

import picker from '@ohos.file.picker';
import { analyzeLeaf, checkHealth } from '../services/HerbiEstimService';
import { AnalyzeResponse, LeafResult } from '../models/HerbiEstimTypes';

@Entry
@Component
struct LeafAnalysisPage {
  @State result: AnalyzeResponse | null = null;
  @State loading: boolean = false;
  @State errorMsg: string = '';
  @State serviceReady: boolean = false;

  aboutToAppear() {
    // 页面加载时检查服务状态
    this.checkServiceStatus();
  }

  async checkServiceStatus() {
    try {
      const health = await checkHealth();
      this.serviceReady = health.status === 'healthy' && health.pix2pix_loaded;
    } catch (e) {
      this.serviceReady = false;
    }
  }

  /**
   * 选择图片并上传分析
   */
  async selectAndAnalyze() {
    // 1. 打开相册选择图片
    const photoPicker = new picker.PhotoViewPicker();
    const selectResult = await photoPicker.select({
      MIMEType: picker.PhotoViewMIMETypes.IMAGE_TYPE,
      maxSelectNumber: 1,
    });

    if (selectResult.photoUris.length === 0) return;

    const imageUri = selectResult.photoUris[0];

    // 2. 调用 API 分析
    this.loading = true;
    this.errorMsg = '';
    this.result = null;

    try {
      this.result = await analyzeLeaf(
        imageUri,
        300,    // dpi
        true,   // isScanned（扫描图设 true，手机拍照设 false）
        true,   // returnImages
        false,  // useSam
      );
    } catch (e) {
      this.errorMsg = (e as Error).message;
    } finally {
      this.loading = false;
    }
  }

  build() {
    Column({ space: 16 }) {

      // 标题
      Text('叶片损伤分析')
        .fontSize(24)
        .fontWeight(FontWeight.Bold)

      // 服务状态
      Row({ space: 8 }) {
        Circle({ width: 10, height: 10 })
          .fill(this.serviceReady ? Color.Green : Color.Red)
        Text(this.serviceReady ? '服务已就绪' : '服务不可用')
          .fontSize(14)
          .fontColor(this.serviceReady ? Color.Green : Color.Red)
      }

      // 上传按钮
      Button('选择图片并分析')
        .width('80%')
        .height(48)
        .enabled(this.serviceReady && !this.loading)
        .onClick(() => this.selectAndAnalyze())

      // 加载状态
      if (this.loading) {
        LoadingProgress().width(48).height(48)
        Text('正在分析叶片损伤，请稍候...')
          .fontSize(14)
          .fontColor(Color.Gray)
      }

      // 错误提示
      if (this.errorMsg) {
        Text(this.errorMsg)
          .fontSize(14)
          .fontColor(Color.Red)
          .padding(12)
          .backgroundColor('#FFF0F0')
          .borderRadius(8)
      }

      // 结果展示
      if (this.result) {
        // 汇总信息
        Column({ space: 8 }) {
          Text(`检测到 ${this.result.summary.num_leaves} 片叶子`)
            .fontSize(18)
            .fontWeight(FontWeight.Bold)

          Text(`平均损伤率: ${(this.result.summary.avg_damage_pct * 100).toFixed(1)}%`)
            .fontSize(28)
            .fontColor('#E53935')
            .fontWeight(FontWeight.Bold)

          if (this.result.summary.total_leaf_area_cm2 !== null) {
            Text(`总叶面积: ${this.result.summary.total_leaf_area_cm2?.toFixed(2)} cm²`)
              .fontSize(14)
            Text(`总完整面积: ${this.result.summary.total_intact_area_cm2?.toFixed(2)} cm²`)
              .fontSize(14)
          }
        }
        .padding(16)
        .backgroundColor('#F5F5F5')
        .borderRadius(12)
        .width('100%')

        // 逐叶结果
        ForEach(this.result.leaves, (leaf: LeafResult) => {
          Row() {
            Column({ space: 4 }) {
              Text(`叶片 #${leaf.leaf_id}`)
                .fontWeight(FontWeight.Medium)
              if (leaf.leaf_area_cm2 !== null) {
                Text(`面积: ${leaf.leaf_area_cm2?.toFixed(2)} cm²`)
                  .fontSize(12)
                  .fontColor(Color.Gray)
              }
            }

            Text(`${(leaf.damage_pct * 100).toFixed(1)}%`)
              .fontSize(20)
              .fontColor('#E53935')
              .fontWeight(FontWeight.Bold)
          }
          .justifyContent(FlexAlign.SpaceBetween)
          .width('100%')
          .padding(12)
          .backgroundColor(Color.White)
          .borderRadius(8)
          .shadow({ radius: 2, color: '#1A000000' })
        })

        // 重建对比图
        if (this.result.leaves.length > 0 && this.result.leaves[0].reconstructed_image) {
          Column({ space: 8 }) {
            Text('重建对比').fontSize(16).fontWeight(FontWeight.Medium)
            Row({ space: 12 }) {
              Column({ space: 4 }) {
                Text('标准化').fontSize(12).fontColor(Color.Gray)
                Image(`data:image/png;base64,${this.result.leaves[0].standardized_image}`)
                  .width(140).height(140).objectFit(ImageFit.Contain)
              }
              Column({ space: 4 }) {
                Text('GAN 重建').fontSize(12).fontColor(Color.Gray)
                Image(`data:image/png;base64,${this.result.leaves[0].reconstructed_image}`)
                  .width(140).height(140).objectFit(ImageFit.Contain)
              }
            }
          }
          .padding(12)
          .width('100%')
        }
      }
    }
    .padding(16)
    .width('100%')
    .height('100%')
  }
}
```

---

## 错误处理

所有非 200 的响应均返回统一的 JSON 错误格式：

```json
{
  "error": "<错误类型>",
  "detail": "<可读的错误描述>"
}
```

### HTTP 状态码对照表

| 状态码 | 含义 | 鸿蒙端处理建议 |
|--------|------|----------------|
| **200** | 成功 | 正常解析 `AnalyzeResponse` |
| **400** | 请求参数错误 | 提示用户：图片格式不支持 / 文件为空 / 参数无效 |
| **401** | 鉴权失败 | 检查 `X-API-Key` 是否正确配置 |
| **413** | 文件过大 | 提示用户压缩图片后重试（限制 20MB） |
| **429** | 请求频率超限 | 提示用户稍后重试（限制 30 次/分钟） |
| **500** | 服务器内部错误 | 提示用户重试。如持续报错，联系后端排查 |
| **503** | 服务未就绪 | 模型正在加载中，稍后自动重试 |

### 推荐错误处理逻辑

```typescript
try {
  const result = await analyzeLeaf(imageUri);
  // 展示结果...
} catch (e) {
  const msg = (e as Error).message;

  if (msg.includes('401')) {
    // API Key 无效
  } else if (msg.includes('413')) {
    // 文件过大，提示压缩
  } else if (msg.includes('429')) {
    // 频率超限，等待后重试
  } else if (msg.includes('503')) {
    // 服务未就绪，自动重试
  } else {
    // 其他错误
  }
}
```

---

## 常见问题

### Q1: `damage_pct` 的值如何理解？

`damage_pct` 是 `0.0`~`1.0` 的浮点数，表示叶片的损伤比例。  
**UI 展示时乘以 100 即为百分比**，例如 `0.286` → 显示 "28.6%"。

### Q2: 什么时候 `leaf_area_cm2` 会返回 `null`？

当请求参数 `is_scanned=false` 时。因为非扫描图无已知的 DPI，无法换算像素面积为物理面积。此时只关注 `damage_pct` 即可。

### Q3: `return_images=true` 时响应体会很大吗？

每张 256×256 的 PNG 图片 Base64 编码后约 **50-150 KB**。如果图中有 N 片叶子，每片返回 2 张图（标准化 + 重建），总增量约 `N × 200KB`。

**建议**：
- 列表页查询时设 `return_images=false`，减小响应体积
- 详情页需要展示重建对比图时才设为 `true`

### Q4: 使用自签名 HTTPS 证书时请求失败

如果服务端使用自签名证书（非 Let's Encrypt 等权威 CA 签发），鸿蒙应用默认会拒绝连接。解决方式：

1. **（推荐）改用 HTTP**：测试 / 内网环境直接用 HTTP，避免证书问题
2. **信任自签名证书**：在 ArkTS 的 HTTP 请求配置中设置 `caPath` 指向自签名证书文件
3. **使用正式证书**：为域名申请 Let's Encrypt 免费证书

### Q5: 手机拍照的叶片图应该怎么传参数？

```typescript
const result = await analyzeLeaf(
  imageUri,
  0,       // dpi: 手机拍照无有意义的 DPI
  false,   // isScanned: 设为 false
  true,    // returnImages
  false,   // useSam
);
// 此时 leaf_area_cm2 和 intact_area_cm2 为 null
// 只关注 damage_pct 即可
```

### Q6: 一张图片中能检测多少片叶子？

理论上无数量限制。服务端自动分割图片中的所有叶片，每片分别分析并返回独立的 `LeafResult`。检测到的总数可通过 `summary.num_leaves` 获取。

### Q7: 请求超时怎么办？

CPU 模式推理通常需 3-5 秒。含多片叶子或高分辨率图片时间更长。建议：
- `readTimeout` 设为 **120 秒**
- 在 UI 上展示带预估时间的加载动画（如 "分析中，预计 5-10 秒..."）

---

## 附录：cURL 调试命令

开发调试时，可用以下命令直接测试 API 是否正常。

### 健康检查

```bash
curl http://<服务器公网IP>/api/v1/health
```

### 分析叶片（不返回图片）

```bash
curl -X POST http://<服务器公网IP>/api/v1/analyze \
  -H "X-API-Key: <你的API密钥>" \
  -F "image=@/path/to/leaf.jpg" \
  -F "dpi=300" \
  -F "is_scanned=true" \
  -F "return_images=false" \
  -F "use_sam=false"
```

### 分析叶片（返回图片）

```bash
curl -X POST http://<服务器公网IP>/api/v1/analyze \
  -H "X-API-Key: <你的API密钥>" \
  -F "image=@/path/to/leaf.jpg" \
  -F "dpi=300" \
  -F "return_images=true"
```

### Windows PowerShell

```powershell
# 健康检查
Invoke-RestMethod -Uri "http://<服务器公网IP>/api/v1/health"

# 分析叶片
$form = @{
    image        = Get-Item "C:\path\to\leaf.jpg"
    dpi          = "300"
    return_images = "false"
    use_sam      = "false"
}
Invoke-RestMethod -Uri "http://<服务器公网IP>/api/v1/analyze" `
  -Method Post `
  -Headers @{ "X-API-Key" = "<你的API密钥>" } `
  -Form $form
```
