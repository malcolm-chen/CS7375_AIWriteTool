# Revision Review：实现规格

> 给编码 agent 的说明：本文件是需求与约束的唯一来源。同目录下的 `prototype.html` 是视觉与交互的参考实现（单文件、mock 数据、可直接在浏览器打开），遇到本文未写明的细节，以原型的行为为准。不要照搬原型的代码结构，按 §2 的技术栈重新组织。

## 1. 目标

研究工具。参与者提交自己写的文本，AI 改写后，系统并排展示原文与改写稿，高亮每处修改，悬停时展示 AI 的修改理由，参与者逐条确认或用语音校准（说出自己的本意）。研究问题是 AI 的解释与人的原意之间的 alignment，因此系统的首要产出是干净、可分析的交互日志，界面次之。

研究者（admin）可以通过一组开关控制界面显示什么，用于构造不同的实验条件。

## 2. 技术栈

| 层 | 选择 | 说明 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite | 状态用 Zustand；样式用 CSS Modules 或 Tailwind，二选一 |
| 后端 | Python FastAPI（或 Node/Express，二选一） | 负责 diff、调用 LLM、存储会话和日志 |
| 存储 | PostgreSQL（开发期可用 SQLite） | 见 §4 数据模型 |
| LLM | 通过环境变量配置 provider 与 model | 改写、解释、judge 三个调用分开配置 |
| 语音 | 开发期 Web Speech API；正式实验用服务端 ASR | 见 §8 |

## 3. 页面与组件

```
/session/:id            参与者页面
  <Header>              标题、图例 <Legend>、进度 <Progress>、管理员入口（仅 admin）
  <ComparePanes>
    <OriginalPane>      原文，对应片段可被联动高亮
    <RevisedPane>       改写稿，修改处渲染为 <EditMark>
  <DetailPanel>         当前修改的详情：<DimensionTag> <DiffLine> <Reason> <Actions>
    <Actions>           “符合我的意思”按钮 + <VoiceButton> 或 <TextCorrection>
  <AdminPanel>          右侧栏，仅 admin 可见（§6）

/admin                  会话列表、创建会话、指定实验条件、导出数据
```

窄屏（< 900px）时两栏改为上下堆叠，管理栏移到内容下方。

## 4. 数据模型

```ts
type Category = 'semantic' | 'wording';
type Dimension = 'certainty_up' | 'certainty_down' | 'hedge_removed' | 'hedge_added'
  | 'meaning_reversed' | 'scope_changed' | 'stance_changed' | 'info_added' | 'info_removed' | 'phrasing';

interface Session {
  id: string;
  participantId: string;
  conditionId: string;           // 对应 §6 的预设
  config: Config;                // 创建时从 condition 复制，之后的修改写入事件日志
  original: string;
  revised: string;
  segments: Segment[];           // 由 diff 生成，两侧共享同一序列
  edits: Record<string, Edit>;
  createdAt: string;
}

type Segment = { kind: 'same'; text: string } | { kind: 'edit'; editId: string };

interface Edit {
  id: string;
  original: string;              // 原文片段，可为空（纯新增）
  revised: string;               // 改写片段，可为空（纯删除）
  originalRange: [number, number];  // 在 original 中的字符偏移
  revisedRange: [number, number];
  explanation: { text: string; model: string; promptVersion: string };
  judge?: { category: Category; dimension: Dimension; confidence: number; rationale: string; model: string; promptVersion: string };
}

interface Decision {
  editId: string;
  type: 'confirmed' | 'corrected';
  modality?: 'voice' | 'text';
  text?: string;                 // 校准内容（语音为转写文本）
  audioRef?: string;             // 仅在参与者同意录音时保存
  ts: string;
}

interface LogEvent {
  sessionId: string;
  ts: string;                    // ISO 时间，客户端时间 + 服务端接收时间各存一份
  type: 'session_start' | 'view' | 'pin' | 'unpin' | 'confirm' | 'correct_start' | 'correct_submit'
      | 'correct_redo' | 'correct_fail' | 'undo' | 'config_change' | 'session_end';
  editId?: string;
  payload?: Record<string, unknown>;
  conditionId: string;
  configSnapshot?: Config;       // config_change 与 session_start 时必填
}
```

`Segment` 序列保证原文和改写稿按同一顺序渲染：`same` 两侧都输出，`edit` 左侧输出 `edit.original`，右侧输出 `edit.revised`。

## 5. Config 开关

| key | 默认 | 作用 | 依赖 |
|---|---|---|---|
| `highlights` | true | 关闭后改写稿不显示任何高亮，详情面板也不出现 | |
| `linkedHighlight` | true | 悬停改写处时，原文对应片段同步标出 | `highlights` |
| `llmJudge` | true | 是否使用 judge 结果。关闭时所有修改用同一种中性高亮，不显示类别和维度 | |
| `categoryColors` | true | 语义改变与仅措辞用不同颜色和下划线样式 | `llmJudge` |
| `dimensionTags` | true | 详情面板显示维度标签（如“确定性 ↑”） | `llmJudge` |
| `hideWordingEdits` | false | 只展示语义改变，仅措辞的修改不高亮、不计入进度 | `llmJudge` |
| `showJudgeDebug` | false | 显示 judge 类别与置信度，只用于调试，正式实验必须关闭 | `llmJudge` |
| `reasons` | true | 显示 AI 修改理由；关闭时改为中性问题“这处修改符合你原本想表达的意思吗？” | |
| `voiceInput` | true | 语音校准；关闭或浏览器不支持时退化为文字输入 | |
| `revertOnCorrect` | true | 校准后改写稿里该处恢复为原文 | |
| `progress` | true | 顶部显示“已审阅 n / m 处修改” | |
| `locale` | 'zh' | 参与者界面语言（zh / en） | |
| `speechLang` | 'zh-CN' | 语音识别语言，与界面语言独立设置 | |

规则：依赖项关闭时，被依赖的开关在管理面板中置灰并提示原因，渲染逻辑一律忽略它的值。重要：`llmJudge = false` 时前端不应再拿到 judge 结果，由后端在下发数据时剥离，避免信息泄漏到 DOM 中。

## 6. 实验条件与管理员

预设条件（可在 `/admin` 中增删改）：

| id | 名称 | 覆盖默认值 |
|---|---|---|
| `full` | A 完整解释 | 无 |
| `noReason` | B 无修改理由 | `reasons: false` |
| `noJudge` | C 无语义分类 | `llmJudge: false` |
| `bare` | D 仅高亮 | `llmJudge: false, reasons: false` |

管理员能力：创建会话时指定条件；在会话页打开右侧“研究设置”栏实时切换开关（每次切换写一条 `config_change` 事件并附完整 config 快照，手动修改后条件显示为“自定义”）；导出单个或全部会话的 JSON 与 CSV；重置会话。

权限：参与者通过一次性链接进入，看不到管理入口；管理员走登录。管理员栏的显隐由后端返回的角色决定，不能只靠前端判断或 URL 参数。

## 7. 交互规格

**预览与固定。** 鼠标悬停或键盘聚焦到改写处，详情面板切换到该修改（预览）。点击或按 Enter/Space 固定，固定后悬停其他修改不再切换，再次点击取消固定。每次切换记一条 `view`，同一修改连续悬停不重复记录。

**确认。** 点击“符合我的意思”，该处高亮变淡，详情面板显示“已确认”与“撤销”。

**语音校准（按住说话）。** 在麦克风按钮上按住开始录音，松开结束；键盘用户按住 Space 或 Enter。录音时按钮变为红色并显示声波动画，旁边提示“正在听，松开结束”，下方实时显示转写文字。录音期间悬停其他修改不切换。松开后展示完整转写，提供“确认校准”和“重新录”两个按钮，确认后才写入 `Decision`。没识别到内容或麦克风被拒绝时，给出具体提示并记 `correct_fail`。

**文字校准。** 点击“不对？写下你的本意”展开文本框，提交时为空要在文本框下方提示错误并阻止提交。

**校准完成。** 详情面板显示用户说的话；若 `revertOnCorrect` 开启，改写稿该处变为绿色并显示原文。可撤销。

**进度。** 只统计当前可见的修改。

## 8. 语音

开发期用浏览器 Web Speech API（Chrome 与 Edge 支持，Firefox 不支持，Safari 部分支持），原型已实现。正式实验建议改为：前端用 `MediaRecorder` 录制，上传到后端，由服务端 ASR（如 Whisper）转写。理由是不同浏览器的识别质量不一致会成为实验混淆变量，而且服务端转写可以保留原始音频供复核。保存音频前必须取得参与者同意，`audioRef` 只在同意时写入。

## 9. 后端流程

```
POST /sessions                 {participantId, conditionId, original}
  1. 改写：调用改写模型得到 revised
  2. Diff：词级 diff（如 diff-match-patch 或 Python difflib，按词切分），
           然后把相邻、间隔不超过 1 个未改词的修改合并为一个短语级 edit
  3. 解释：对每个 edit 调用解释模型，输入完整原文、完整改写稿和该 edit 的位置，
           输出一句话理由（使用参与者语言）
  4. Judge：对每个 edit 独立调用 judge 模型，输出 JSON（见下），不输入第 3 步的解释
  5. 存储并返回 Session（按 conditionId 剥离 judge 字段）
GET  /sessions/:id
POST /sessions/:id/events      批量上报事件，客户端每 5 秒或页面隐藏时 flush
POST /sessions/:id/decisions
PATCH /sessions/:id/config     仅 admin
GET  /admin/export?format=json|csv
```

Judge 输出格式（要求模型只返回 JSON，后端做 schema 校验，失败重试一次，仍失败则标记 `judge: null` 并在管理端提示）：

```json
{
  "category": "semantic",
  "dimension": "certainty_up",
  "confidence": 0.94,
  "rationale": "‘might’ expresses possibility; ‘will’ expresses commitment."
}
```

Judge 判定标准写进 prompt：如果一个母语读者会认为作者的立场、确定性、范围、事实内容或逻辑关系发生了变化，为 `semantic`；只是用词、语序、语法或正式程度变化而命题不变，为 `wording`。所有 prompt 加版本号，随结果一起存储。

研究设计上需要注意：解释是由改写模型对自己修改的"自我解释"，还是由另一个模型事后生成，会影响研究结论。系统应支持两种模式，通过配置选择，并在数据里记录。

## 10. 视觉规范

| token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--paper` | #FAFAF7 | #16181B | 页面背景 |
| `--surface` | #FFFFFF | #1E2125 | 面板 |
| `--ink` / `--ink-2` / `--ink-3` | #1D2125 / #5B6168 / #8A9097 | #E8E9EA / #A9AEB4 / #7C8187 | 正文 / 次要 / 提示 |
| `--sem-*` | bg #FBE7EF，字 #8A1C47，线 #C8366F | bg #4A1A2E，字 #F6C6D8，线 #E0669A | 语义改变，实线下划线 |
| `--word-*` | bg #E8EBFB，字 #2E3A8C，线 #6574D8 | bg #232A55，字 #CDD3FA，线 #8B97EA | 仅措辞，虚线下划线 |
| `--plain-*` | bg #EFEFEA，线 #8A9097 | bg #2A2D31，线 #7C8187 | 未分类时的中性高亮 |
| `--ok-*` | bg #E3F2E8，字 #1E6B3D | bg #173A26，字 #BFE6CD | 已校准 |

字体：被审阅的文本用 Source Serif 4，18px，行高 2，每行不超过约 62 个字符；界面其余部分用 IBM Plex Sans。颜色只用于标示修改，其他元素保持灰白。类别同时用颜色和下划线样式（实线与虚线）区分，保证色弱用户也能分辨。

## 11. 可访问性

修改处 `role="button"`、可 Tab 聚焦，固定状态用 `aria-pressed`。详情面板 `aria-live="polite"`。管理开关用 `role="switch"`。尊重 `prefers-reduced-motion`（关闭声波动画）与 `prefers-color-scheme`。

## 12. 验收标准

1. 用 §4 的 mock 数据打开会话页，界面与 `prototype.html` 在浅色和深色模式下一致。
2. §5 每个开关切换后立即生效，依赖关系正确，且每次切换都产生带完整 config 快照的 `config_change` 事件。
3. 四个预设条件分别渲染出预期界面；`noJudge` 和 `bare` 条件下，浏览器开发者工具中找不到任何 judge 字段。
4. 按住说话、松开结束、确认与重新录在 Chrome 中可用；不支持语音的浏览器自动退化为文字输入并显示提示。
5. 文字校准提交空内容时被阻止并显示错误。
6. 所有交互都有对应事件，导出的 JSON 和 CSV 能还原每位参与者对每处修改的完整操作序列。
7. 参与者账号无法看到或调用任何管理功能（前后端都要验证）。
8. 后端 diff 对中英文混排文本正确切词，相邻小修改按规则合并。
9. judge 返回非法 JSON 时有重试与降级，不阻塞会话创建。

## 13. 待定问题

需要研究者确认：参与者文本的典型长度（决定是否需要长文本的同步滚动与修改导航）；是否允许参与者修改自己已确认过的决定（原型允许撤销）；解释模式选自我解释还是事后解释；是否保存语音原始音频。
