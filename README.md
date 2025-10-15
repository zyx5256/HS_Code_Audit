# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

HS Code 审计工具，从 PDF 发票中提取货物信息，并与 Excel 中的标准 HS Code 对比，自动发现不一致项。

### 代码架构（按数据流）
```
audit.py                      # HS Code 审计主程序（统一入口）
├── pdf_extractor/
│   ├── reader.py             # PDF 文本读取（PyMuPDF + OCR）
│   ├── preprocessor.py       # 文本预处理（换行合并、清理）
│   ├── extractor.py          # 内容抽取算法（截断、规则匹配、发票解析）
│   ├── validator.py          # 数据校验（三层校验）
│   ├── writer.py             # 输出模块（JSON/CSV/JSONL）
│   └── cli.py                # 命令行接口（协调各模块）
├── excel_extractor.py        # Excel 提取模块（Item → HScode 映射）
└── comparator.py             # 对比模块（验证 HS Code 一致性）

get_text_from_pdf.py          # PDF 提取工具（独立使用）
```

**审计流程**：
```
PDF 发票                      Excel 映射表
  ↓                              ↓
[pdf_extractor]              [excel_extractor]
  ↓                              ↓
提取货物+HScode              提取 Item→HScode 映射
  ↓                              ↓
  └──────→ [comparator] ←────────┘
                ↓
          对比验证（按 U11 Code）
                ↓
          错误报告（CSV + 控制台）
```

### 业务目标
从发票 PDF 中自动提取货物信息，用于海关合规审计。

### 实施路径
1. **基础提取**：`extract_text_from_pdf()` 从 PDF 提取原始文本
2. **规律探索**：`dump` 子命令导出带坐标的行/块/词，人工分析结构
3. **自动化提取**：`extract_invoice_items()` 按发票格式自动提取+三层校验（已实施）
4. **规则定制**：`extract` 子命令支持自定义规则文件（适配其他发票格式）

## 依赖安装

### 基础依赖（必需）
```bash
pip install -r requirements.txt
```

### OCR 支持（可选 - 处理扫描件PDF时需要）

**方法1：使用 Chocolatey（推荐）**
```bash
# 安装 Chocolatey 包管理器（如未安装）
# 访问：https://chocolatey.org/install

# 安装 OCR 依赖
choco install ghostscript tesseract
```

**方法2：手动安装**

1. **安装 Ghostscript**（PDF处理工具）
   - 下载地址：https://ghostscript.com/releases/gsdnld.html
   - 选择 `Ghostscript 10.x for Windows (64 bit)` 下载
   - 安装后添加到系统PATH：`C:\Program Files\gs\gs10.xx.x\bin`

2. **安装 Tesseract OCR**（文字识别引擎）
   - 下载地址：https://github.com/UB-Mannheim/tesseract/wiki
   - 下载 `tesseract-ocr-w64-setup-5.x.x.exe`
   - 安装时**勾选"简体中文语言包"（chi_sim）**
   - 安装后添加到系统PATH：`C:\Program Files\Tesseract-OCR`

3. **配置系统环境变量（PATH）**
   ```
   右键"此电脑" → 属性 → 高级系统设置 → 环境变量
   → 系统变量 → Path → 编辑 → 新建
   添加：
   C:\Program Files\gs\gs10.02.1\bin
   C:\Program Files\Tesseract-OCR
   ```

4. **验证安装**（需重启命令行窗口）
   ```bash
   gs --version
   tesseract --version
   ```

**注意：**
- 有文本层的PDF不需要OCR即可处理
- OCR仅在遇到扫描件（无文本层）时自动触发
- 如果不安装OCR，扫描件PDF会报错并跳过

## 常用命令

### 1. HS Code 审计（推荐 - 完整流程）
```bash
# 基础用法：对比 PDF 发票和 Excel 映射表
python audit.py invoice.pdf hscode_mapping.xlsx

# 自定义列名
python audit.py invoice.pdf hscode_mapping.xlsx --item-col "Item" --hscode-col "HScode USA "

# 指定输出文件
python audit.py invoice.pdf hscode_mapping.xlsx -o errors.csv

# Debug 模式（保存中间 JSON 文件）
python audit.py invoice.pdf hscode_mapping.xlsx --debug --debug-dir ./debug
```

**输出说明**：
- 如果有错误：打印错误列表 + 生成 CSV 报告
- 如果没有错误：输出 "✓ Verification successful! All HScodes match."

### 2. PDF 提取（独立使用）
```bash
# 自动提取发票货物+三层校验
python get_text_from_pdf.py auto invoice.pdf --out result.json

# 扫描件+调试模式
python get_text_from_pdf.py auto invoice.pdf --ocr chi_sim+eng --debug
```

### 3. Excel 提取（独立使用）
```bash
# 提取 Item 和 HScode 映射
python excel_extractor.py hscode_mapping.xlsx -o mapping.json

# 自定义列名
python excel_extractor.py file.xlsx --item-col "Item" --hscode-col "HScode USA "
```

### 4. 探索模式（分析 PDF 结构）
```bash
# 导出带坐标的行（用于分析提取规律）
python get_text_from_pdf.py dump invoice.pdf --mode lines --out lines.csv

# 导出版面块
python get_text_from_pdf.py dump invoice.pdf --mode blocks --out blocks.jsonl

# 智能合并相邻行+截断
python get_text_from_pdf.py dump invoice.pdf --merge --truncate "SAY U.S.DOLLARS" --out lines.csv

# 指定页码
python get_text_from_pdf.py dump invoice.pdf --pages 1,2 --out lines.csv
```

### 5. 规则提取（定制化）
```bash
# 基于规则文件按页码+行号精确提取
python get_text_from_pdf.py extract invoice.pdf --rules rules.json --out result.json
```

### 6. 基础文本提取（兼容旧用法）
```bash
# 预览 PDF 文本
python get_text_from_pdf.py invoice.pdf

# 输出到文件
python get_text_from_pdf.py invoice.pdf --out-legacy text.txt

# 使用版面块模式
python get_text_from_pdf.py invoice.pdf --blocks --out-legacy text.txt
```

## 核心功能架构

### 1. PDF 文本读取（`reader.py`）
**职责**：打开 PDF、提取原始文本/行/块/词、OCR 处理
- **输入参数**：
  - `pdf_path`: PDF 文件路径
  - `return_pages`: 是否按页返回（默认 True）
  - `sort_text`: 是否按阅读顺序排序（默认 True）
  - `use_ocr_fallback`: 遇到空白页是否 OCR（默认 False）
  - `ocr_lang`: OCR 语言，如 `"chi_sim+eng"`（中英混合）
  - `layout_mode`: `"text"`（阅读顺序）或 `"blocks"`（版面块）
  - `pages`: 指定页码列表（1-based），None 表示全部
- **返回结构**：`ExtractResult` 字典
  ```python
  {
    'ok': bool,
    'pages': List[str],  # 每页文本
    'meta': {'src': str, 'total_pages': int, 'joined_chars': int, ...},
    'error': Optional[str]
  }
  ```

### 2. 文本预处理（`preprocessor.py`）
**职责**：智能合并相邻行、文本清理

**核心函数**：
- `merge_adjacent_lines()` - 智能合并相邻行（解决换行拆分问题）
  - 合并条件：同一页 + 水平重叠 > 80% + 垂直间距 < 5px
  - 示例：`"YCV5-43GTLA-1-" + "U3"` → `"YCV5-43GTLA-1-U3"`
- `clean_text()` - 文本清理（中文括号→英文括号）

### 3. 内容抽取算法（`extractor.py`）
**职责**：截断处理、规则提取、发票解析

**核心函数**：
- `truncate_at_marker()` - 截断文本（过滤底部无关内容）
- `extract_by_rules()` - 基于规则文件提取字段（页码+行号）
- `extract_invoice_items()` - 发票货物自动提取
  - 识别 "DESCRIPTION OF GOODS" 块
  - 每 7 行为一组货物信息
  - 遇到 "SUB TOTAL" 标记块结束

### 4. 数据校验（`validator.py`）
**职责**：三层校验发票数据

**校验层级**：
1. 货物级：`quantity × unit_price == amount`
2. 块级：`subtotal == Σ(quantity)`, `total_usd == Σ(amount)`
3. 全局：`global_total_quantity == Σ(subtotal)`, `global_total_usd == Σ(total_usd)`

**输出示例**：
```json
{
  "goods_blocks": [
    {
      "block_index": 1,
      "items": [
        {
          "hs_code": "8481.80.9090",
          "description": "YCV5-43GTLA-1-U3",
          "quantity": "100",
          "unit_price": "$12.34",
          "amount": "$1,234.00"
        }
      ],
      "subtotal": "100",
      "total_usd": "$1,234.00"
    }
  ],
  "global_total_quantity": "100",
  "global_total_usd": "$1,234.00",
  "validation_errors": []
}
```

### 5. 输出模块（`writer.py`）
**职责**：格式化输出到 JSON/CSV/JSONL

**核心函数**：
- `write_json()` - 输出 JSON 文件
- `write_csv()` - 输出 CSV 文件
- `write_jsonl()` - 输出 JSONL 文件（每行一个 JSON）
- `write_auto()` - 根据文件扩展名自动选择格式
- `print_json()` / `print_jsonl()` - 输出到 stdout

## 典型工作流程

### 场景 1：标准发票（已知格式）
```bash
# 直接使用自动提取+三层校验
python get_text_from_pdf.py auto invoice.pdf --out result.json

# 检查 validation_errors 字段确认数据准确性
```

### 场景 2：扫描件发票
```bash
# 启用 OCR（需先安装 Tesseract）
python get_text_from_pdf.py auto invoice.pdf --ocr chi_sim+eng --out result.json --debug
```

### 场景 3：新格式发票（需探索规律）
```bash
# 1. 导出带坐标的行
python get_text_from_pdf.py dump invoice.pdf --mode lines --out lines.csv --merge

# 2. 用 Excel 打开 lines.csv，观察规律：
#    - HS Code、货物描述在哪些行？
#    - 是否有关键词标识（如 "DESCRIPTION OF GOODS"）？
#    - 多个货物如何分隔？

# 3. 编写规则文件 rules.json
# 4. 用 extract 子命令测试
python get_text_from_pdf.py extract invoice.pdf --rules rules.json --out result.json
```

## 重要实现细节

### 智能文本合并（`preprocessing.py:215`）
解决货物编码因换行被拆分的问题（如 "YCV5-43GTLA-1-" + "U3" → "YCV5-43GTLA-1-U3"）

**合并条件**（同时满足）：
1. 同一页
2. 水平位置重叠 > 80%（在同一列）
3. 垂直间距 < 5 像素（紧密相邻）

### OCR 处理策略
- **OCR 兜底**：`use_ocr_fallback=True` 时，仅对文本层为空的页执行 OCR
- **OCR 前处理**：`dump/extract` 子命令使用 `ocrmypdf --skip-text` 避免覆盖现有文本层
- **临时文件**：OCR 处理时创建临时目录（`tempfile.mkdtemp`），处理完成后自动清理

### PyMuPDF 行提取问题与解决方案

**问题描述**：
PyMuPDF 的 `get_text('dict')` 在提取文本时，可能会将**垂直位置不同**的文本错误合并成一行。

**典型现象**：
- 正常行高度：约12px
- 异常行高度：约18px（合并了两行文本）
- 坐标特征：y1（底部）相同，但y0（顶部）差异大

**根本原因**：
PyMuPDF 使用**底部对齐（baseline alignment）**策略判断"什么是一行"。当两个文本块的底部（y1）接近时，即使顶部（y0）差异很大，也可能被合并。

**当前解决方案**：
在 `preprocessor.py` 中增加 `split_abnormal_height_lines()` 函数，在合并行操作**之前**检测并拆分异常行高的行。

**备用方案（未实施）**：
如果异常行高检测方案效果不佳，可考虑切换到 `get_text('words')` 模式：
1. 提取所有words（每个word有独立坐标）
2. 按严格的垂直位置判断（y0和y1都接近）重新组装成行
3. 完全控制"什么是一行"的逻辑

优点：根本性解决PyMuPDF的底部对齐误判
缺点：需要重写 `reader.py` 的 `_lines_via_dict()` 函数，逻辑复杂度增加

### 版本兼容性
- **PyMuPDF 版本**：`_lines_via_dict()` 使用 `get_text('dict')` 解析，兼容旧版 PyMuPDF
- **日志系统**：使用 `logging` 模块，CLI 默认 INFO 级别，`--debug` 启用 DEBUG

## 调试技巧

### 检查提取结果
```bash
# 启用调试输出，查看中间步骤
python get_text_from_pdf.py auto invoice.pdf --debug

# 导出 dump 结果，人工对比
python get_text_from_pdf.py dump invoice.pdf --mode lines --merge --out debug.csv
```

### 校验失败排查
当 `validation_errors` 非空时：
1. 检查是否有换行拆分问题（`dump --merge` 对比）
2. 检查截断标记是否正确（如 "SUB TOTAL"）
3. 使用 `--debug` 查看中间提取结果

### OCR 问题排查
```bash
# 测试 OCR 是否正常工作
python -m ocrmypdf --version
python -m ocrmypdf --skip-text -l chi_sim+eng input.pdf output.pdf

# Windows 中文路径问题：复制文件到英文路径测试
```

## 注意事项

- **Windows 路径**：路径包含中文（如 OneDrive 中的"轮岗"），在某些 OCR 场景可能报错，建议测试时用英文路径
- **Tesseract 语言包**：中文 OCR 需安装 `chi_sim.traineddata`（简体）或 `chi_tra.traineddata`（繁体）
- **PDF 加密**：当前仅尝试空密码,密码保护的 PDF 会返回错误
- **发票格式**：`auto` 子命令针对特定发票格式优化（每 7 行一组货物），其他格式需用 `dump` + `extract` 定制规则

---

# 表格提取算法设计

## 1. 算法演进

### 1.1 旧方案（固定7行算法）
**局限性**：
- 假设每个货物占用固定7行，无法适配不同格式
- 依赖文本行提取，容易受PDF渲染差异影响
- 硬编码7列结构，无法处理更多列

### 1.2 当前方案（基于矩形线分割）
**核心发现**：发票PDF使用**竖线（垂直矩形）**分隔列，而非单元格矩形。

**关键修复**（2025-10-14）：
- **问题**：之前用单元格矩形边界定义列，导致宽度超过100px的列（如Amount列108px）被过滤掉
- **根因**：`identify_columns_from_header` 使用 `5 < width < 100` 过滤，Amount列被遗漏
- **修复**：改为提取竖线（width < 2），用相邻竖线之间的空间定义列边界
  ```python
  # 提取竖线作为列分隔
  vertical_lines = [r for r in rectangles if (r['x1'] - r['x0']) < 2]
  # 用相邻竖线之间定义列
  for i in range(len(unique_x) - 1):
      column = (unique_x[i], unique_x[i+1])
  ```
- **效果**：正确识别所有列（包括宽度>100px的列），unit_price和amount字段不再混淆

**优势**：
- ✅ 支持任意列数的表格（已测试7-10列）
- ✅ 基于PDF原生矩形结构，不受文本渲染影响
- ✅ 自动识别多个表格块（DESCRIPTION OF GOODS → SUB TOTAL）
- ✅ 精确提取单元格内容（通过竖线边界）

## 2. 表格提取流程

### 2.1 结构识别
```python
# 步骤1：提取所有矩形（单元格+竖线）
drawings = page.get_drawings()
rectangles = extract_table_rectangles(page)

# 步骤2：识别列边界（基于竖线）
vertical_lines = [r for r in rectangles if width < 2]
columns = identify_columns_from_header(page, header_y)

# 步骤3：识别表格块（DESCRIPTION → SUB TOTAL）
regions = find_table_regions(page)  # [(start_y, end_y), ...]
```

### 2.2 数据提取
```python
for page_num, start_y, end_y in regions:
    # 聚类数据行（按y坐标，过滤宽度异常矩形）
    data_rows = cluster_rows_by_y(rectangles, start_y, end_y)

    for row_y, cells in data_rows:
        # 提取单元格内容
        for cell in cells:
            content = extract_cell_text(words, cell)
            field_name = assign_cell_to_column(cell['x0'], columns)
            item_data[field_name] = content
```

### 2.3 关键参数
```python
# 列边界识别
vertical_line_width_threshold = 2      # 竖线宽度阈值
column_x_merge_tolerance = 2           # 相邻竖线合并容忍度

# 行聚类
row_y_clustering_tolerance = 2         # 同一行的y坐标容忍度
cell_width_filter = (5, 150)           # 过滤异常宽度矩形

# 单元格内容匹配
cell_boundary_tolerance = 2            # 文字匹配边界容忍度
```

## 3. 核心代码位置

### 表格提取（extractor.py）
- `identify_columns_from_header()` - 基于竖线识别列（第179行）
- `cluster_rows_by_y()` - 按y坐标聚类行（第260行）
- `extract_cell_text()` - 提取单元格文字（第296行）
- `assign_cell_to_column()` - 分配单元格到列（第321行）
- `extract_invoice_goods_items()` - 主提取函数（第395行）

### 文本预处理（preprocessor.py）
- `split_abnormal_height_lines()` - 拆分异常行高（解决PyMuPDF底部对齐问题）
- `merge_adjacent_lines()` - 智能合并相邻行（解决换行拆分）
- `split_wide_lines()` - 拆分宽行（解决两列合并）

### 数据校验（validator.py）
- 三层校验：货物级、块级、全局

## 4. 已知问题与解决方案

### 4.1 PyMuPDF行提取问题
**问题**：`get_text('dict')` 使用底部对齐策略，可能错误合并垂直位置不同的文本
**特征**：异常行高度（18px vs 正常12px）
**解决方案**：`split_abnormal_height_lines()` 在合并行之前拆分异常行高

### 4.2 竖线分隔识别
**问题**：部分发票无竖线，或竖线不完整
**解决方案**：回退到单元格矩形边界（旧方法）
```python
if not vertical_lines:
    # 回退：使用单元格矩形
    header_rects = [r for r in rectangles if 5 < width < 100]
```

### 4.3 跨页表格
**当前方案**：按页独立处理，通过 `rows` 参数传递页码信息
**限制**：一个块的SUB TOTAL必须在同一页
**未来优化**：支持跨页块识别

## 5. 测试覆盖

### 已验证格式
- invoice2.pdf: 8列，9个块，11个items ✓
- invoice3.pdf: 7列，23个块，49个items ✓
- invoice4.pdf: 8列（含Amount宽列），10个块，24个items ✓
- invoice5.pdf: 9列，4个块 ✓

### 边界情况
- ✅ 空单元格
- ✅ 多行单元格（如长描述）
- ✅ 宽度>100px的列
- ✅ 扫描件（OCR兜底）
- ✅ 中文括号清理

## 6. 性能指标

- 单页处理时间：< 0.1秒
- 内存占用：< 10MB
- 准确率：99%+（基于已测试发票）

---

## Context记录（最近修复）

**修复时间**：2025-10-14

**问题发现**：
- invoice4.pdf的Block 1 Item 1未参与HScode对比
- unit_price字段包含amount的值（"3.2 128"），amount字段为空

**根本原因**：
1. Amount列矩形宽度108px，超过 `< 100` 过滤阈值
2. 代码使用单元格矩形边界（而非竖线）定义列
3. Amount列被忽略，其内容被错误分配给相邻的unit_price列

**修复方案**：
1. **identify_columns_from_header**：改为提取竖线（width < 2），用竖线间距定义列
2. **cluster_rows_by_y**：过滤 `5 < width < 150` 避免整行大矩形干扰

**修复效果**：
- ✅ 正确识别8列（包括Amount列）
- ✅ unit_price="3.2", amount="128" （字段不再混淆）
- ✅ Block 1 Item 1参与HScode对比（无validation错误）
- ✅ PDF validation errors: 0

**关键代码**：
- `extractor.py:179-257` - identify_columns_from_header（基于竖线）
- `extractor.py:260-293` - cluster_rows_by_y（过滤异常宽度）
- to
