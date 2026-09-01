---
name: resume-optimization-workflow
description: 简历评分+优化全流程（PDF提取→百分制评分→40项清单润色→打印友好HTML导出→头像提取）。触发词：优化简历、简历评分、简历润色、改简历、polish resume。
---

# 简历优化全流程

## 工作流（7 步）

1. **提取 PDF 文本**：Read 工具读 PDF 若失败（二进制），用 venv 的 pdfplumber 提取文本。
   ```bash
   VENVPY="<你的 Python 虚拟环境 python.exe 绝对路径>"
   "$VENVPY" -m pip install pdfplumber -q
   "$VENVPY" -c "import pdfplumber; ..."  # 逐页 extract_text()
   ```

2. **百分制基线评分**：5 维度（内容30/结构25/语言20/ATS15/影响力10）→ 总分+等级+Top3优势+优先级改进项(🔴🟡🟢)+Before→After示例+5步行动计划。

3. **40 项清单润色**：逐项检查联系方式/摘要/经历/教育/技能/语法/排版/ATS，输出精修版全文 + 分级变更摘要。

4. **核心判断标准（重要）**：
   - **核心业绩 = 量化 + 超预期 + 竞争力**；底线达成（0失误/没出错）、职责完成（搭建投入运营）、稳定出单（常态）→ 一律降级到「工作职责」，不进「核心业绩」。
   - **时间线真实性**：某阶段业绩必须与该时期技术发展吻合。例：2021-2024 期间 AI/Playwright 未盛行，不能把 AI 能力挂靠该阶段业绩；当前具备但不属于该阶段的能力 → 放技能模块，不挂历史业绩。
   - **严禁编造**：量化须基于用户素材合理推演；无真实数据用"显著提升"等推演式表述并标注待确认。

5. **生成 HTML + MD 双文件**：HTML 内联 CSS（可打印），MD 作工作主格式。每次改动两文件同步。

6. **打印友好 HTML 模板要点**：
   - 技能用**纯文本 · 分隔**，不用胶囊框框（框框打印费墨+ATS不友好）。
   - 联系方式去 emoji，用文字标签（电话/邮箱）。
   - 配色减色块，标题用文字色不用大块背景。
   - **分页关键**：`.exp { page-break-inside: avoid }` 会导致长段被整段推下页、上页留 1/3 空白 → **去掉该规则**，改用 `h2/h4/.exp-head { page-break-after: avoid }` 只防标题孤立。
   - `@media print` 加 `print-color-adjust: exact` 保彩色标题。

7. **头像提取**：PDF 内嵌图片用 PyMuPDF 提取。
   ```bash
   "$VENVPY" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PyMuPDF  # 国内镜像，否则19.8MB下载断流
   "$VENVPY" -c "import fitz; doc=fitz.open(pdf); [doc.extract_image(img[0]) for img in page.get_images(full=True)]"
   ```
   提取后 `<img class="avatar" src="..." >` 放 header 右侧，flex 布局。

## 省积分经验（给迭代式任务）

- 对话式逐字打磨每轮重传全部上下文，成本高。**攒 3-5 处修改一次性提**，别一条一条发。
- 会话变长后底薪大，大改建议**新开会话 + 贴定稿文件路径**，只说"基于这个改XX"。
- 小改（改年龄/删行）让用户自编辑文件，零积分。

## 评分参考基线

| 等级 | 分数 | 含义 |
|---|---|---|
| A+ | 90-100 | 卓越 |
| A | 85-89 | 优秀 |
| B+ | 80-84 | 良好可投递 |
| D | 55-59 | 需重大改进 |

案例：亚马逊运营简历原始 56/D → 优化后 86/A 级边缘（主要靠：删异常低薪资改面议、修错别字、重建技能模块、量化业绩、厘清时间线、AI 能力作差异化技能凸显）。
