# cs 首次运行检测并关闭 Claude Code 会话自动清理 — 设计文档

日期:2026-09-15(2026-09-16 按 review 修订)
状态:已获用户批准;三方 review(zcode/claude/trae,board thread #5)
3/3 通过,10 条 minor 意见(M1-M9)已修订落实

## 背景与动机

Claude Code 默认每 30 天自动删除会话转录(`cleanupPeriodDays` 默认 30),
`~/.claude/projects/` 里超过 30 天的 `.jsonl` 会被清掉。用户发现 `cs`
列出的会话数**远少于注册过的项目数**(检查时刻动态快照:
`~/.claude.json` 记录 21 个项目目录,而 `~/.claude/projects/` 里仅个
位数项目还有转录,多数只剩空 `memory/` 目录——文件系统是活的,
Claude Code 持续写入/清理,精确数每次检查都变,引用数字须注明快照)。
**年龄悬崖签名**(比数量对比更硬的证据):现存转录 9 个 ≤2 天 +
1 个恰好 29 天,**零个 >30 天幸存者**——30 天清理生效的典型特征。

解决方法是把 `~/.claude/settings.json` 顶层加上
`"cleanupPeriodDays": 3650`。本设计让 `cs` 在首次运行时自动完成这件事。

## 需求(用户三条,逐条落实)

1. **用户知情**:cs 首次运行时检查自动清理是否仍在生效;在生效则提示
   用户是否关闭。
2. **安全第一**:修改方式绝不破坏用户已有配置。
3. **测试覆盖**:改动有测试用例覆盖。

## 已确认的决策(用户逐项确认)

- 保留时长:**3650 天(10 年)**。不用 `0`:GitHub issue
  anthropics/claude-code#23710 报告 `cleanupPeriodDays: 0` 会**静默
  停止全部转录落盘**(比清理更糟;另一来源称 0 会被校验拒绝、最小值
  1,未能独立复现——无论哪种,0 都有害),大数值是唯一安全做法。
- 拒绝后:**永不再问**,但明确提示用户"以后想改可以让自己的 Claude
  帮忙修改 settings.json"。
- 提示存在即不问:`cleanupPeriodDays` 键已存在(无论值大小)视为用户
  或策略的明确选择,cs 绝不二次打扰。

## 方案选择(两轴,均已选 A)

### 轴 1:提示逻辑放哪 → cs.py 内部(TTY 门控)

- `main()` 里、**stdout 是 TTY 时**才检查并提示,y/N 从 `/dev/tty` 读
  (与 install.sh 的 `prompt_yesno` 同一手法)。
- 理由:wrapper 有 bash/zsh 两份(agent.md 不变量 #5 要求双份同步),
  放 cs.py 一份代码搞定;`cs 3`(resume)、`--complete`、管道场景因
  stdout 非 TTY **自动跳过**,无需特判,天然满足不变量 #2
  (`--resolve` stdout 必须纯净)。
- 落选方案 B(新增 `--check-cleanup` 后端模式 + wrapper 提示):严格
  遵循"交互在 wrapper"惯例,但逻辑要写两遍、install.sh 双份维护、难测试。

### 轴 2:怎么改 settings.json → 文本级微创插入 + 六步防线

落选的 JSON round-trip(loads→改→dumps)会重排整个文件:unicode 转义
(`…`→`…`)、浮点格式、缩进都可能变,违背"不碰用户已有配置"。

## 详细设计

### 新增模块常量(与 PROJECTS_DIR 同模式,可被测试 monkeypatch)

```python
SETTINGS_FILE = os.path.expanduser("~/.claude/settings.json")
STATE_FILE    = os.path.expanduser("~/.claude/cs-state.json")
CLEANUP_DAYS  = 3650
```

### 检测语义(保守)

`cleanup_status(settings_path)` 返回:
- `"default"` — 文件不存在,或文件里没有 `cleanupPeriodDays` 键
  (= 默认 30 天清理在生效,值得提示);
- `"set"` — 键存在(无论值;哪怕 3 天也是明确选择,不提示)。

文件存在但出现以下任一情况 → 检测返回 `"unknown"`,不提示、不改、
不记 marker(见"失败处理"):
- JSON 非法;
- 文件不可读(权限 / IO 错误,如 chmod 000);
- 内容是合法 JSON 但不是对象(数组 / 字符串等,无法安全判断键)。

### 触发条件(三条全满足才提示)

1. `~/.claude/cs-state.json` 里没有 `cleanup_prompt` 键。文件读不了
   或 JSON 非法 → 一律视为"未问过",**重问一次**——用户决策不可读
   时,重问比静默跳过安全,且重问是自愈的(再答一次就写入合法
   marker,坏状态不会持续);
2. `cleanup_status() == "default"`;
3. `sys.stdout.isatty() and sys.stderr.isatty()` **双条件**(交互式;
   捕获输出/管道/补全自动跳过)。必须双门控:只查 stdout 时,
   `cs 2>log`(stdout 是 TTY、stderr 进文件)场景提示写进 log
   不可见,但代码阻塞读 `/dev/tty`,用户视角是**卡死**——本轮
   review 最重要的一条发现。

**检查位置**:argparse 成功分派之后、进入子命令逻辑前(避免
`cs --typo-flag` 先弹提示再报错)。所有 stdout 为 TTY 的子命令入口
统一检查:裸 `cs`/`-f`/`-c`/`-n` 均可触发;`--resolve`/`--delete`/
`--complete` 因输出被 `$(...)` 捕获自动跳过。

**marker 不变量**:marker 只在成功路径写;坏/缺 marker 一律视为
"未问"。两个方向都自愈(缺 marker → 重问;文件改了 marker 没写成 →
下次检测为 "set" 不再问)。

### 安全修改六步防线 `disable_cleanup()`

1. **读原文**:文件不存在按 `{}` 处理(创建新文件);
2. **改前验证**:`json.loads(原文)` 必须成功,否则放弃不动手;
3. **微创插入**:在开括号 `{` 后插入 `"cleanupPeriodDays": 3650,`
   (带尾逗号,首键位置),按原文件格式分三种情况:
   - 多行 pretty 格式(`{` 后是换行)→ 插入新的一行
     `\n  "cleanupPeriodDays": 3650,`,其余行字节级不变;
   - 空对象(只含空白)→ 直接写
     `{\n  "cleanupPeriodDays": 3650\n}`;空白判定用
     `re.fullmatch(r'\{\s*\}', text)`,命中 `{}`、`{ }`、`{\n}`、
     `{\n  }` 等全部形态;
   - 单行有内容(如 `{"model":"sonnet"}`)→ 在 `{` 后内联插入
     ` "cleanupPeriodDays": 3650,`;
   三种情况均以第 4 步的解析+比对兜底,格式分支只为美观,不影响正确性;
4. **改后验证**:新文本 `json.loads` 成功,且结果 dict ==
   原 dict + 新键。**等值校验是六步防线的核心,不可省略**——它让
   第 3 步任何插入错误都变成"回滚不改",即使格式分支逻辑写错也
   不会破坏文件;
5. **备份**:原文件先复制为
   `~/.claude/settings.json.cs-bak-<YYYYmmddTHHMMSS>`(时间戳防覆盖
   旧备份);**轮转保留最近 5 份**,更旧的自动删除;
6. **原子写**:同目录临时文件写完 `os.replace`(崩溃安全)。

任何一步失败 → 原文件零影响,cs 其余功能不受影响。

### 交互流程与文案(英文,与 cs 现有消息风格一致;全部走 stderr)

```
cs: notice: Claude Code auto-deletes session transcripts older than 30 days
    (default cleanupPeriodDays). That's why old sessions vanish from this list.
    Keep sessions for 10 years instead (set cleanupPeriodDays=3650)? [y/N]
```

- **y** → 执行六步修改。成功:
  `cs: auto-cleanup disabled (3650 days), backup at <backup-path>`,
  写 marker `{"cleanup_prompt": "accepted"}`。
- **N / 回车 / EOF**(默认否):
  `cs: OK, keeping the default 30-day cleanup. To change later, ask Claude to set "cleanupPeriodDays" in ~/.claude/settings.json`,
  写 marker `{"cleanup_prompt": "declined"}`,永不再问。
- y/N 从 `/dev/tty` 读;打不开 `/dev/tty` 视为 N(同 install.sh 手法)。

### 失败处理

**顺序不变量:先改 settings.json、后写 marker,不可颠倒**——颠倒了
会出现"marker 记了 accepted 但文件没改",则永不再问且从未生效。该
顺序还带自愈性质:settings 改成功而 marker 写失败 → 下次检测为
`"set"` → 不再问,静默自愈,无重复打扰。

修改失败(JSON 非法、IO 错误等):**不写 marker**(下次运行可重试),
stderr 输出失败原因 + 手动指引
(`ask Claude to set "cleanupPeriodDays" in ~/.claude/settings.json`)。
settings.json 非法时 Claude Code 自身也会出问题,属罕见暂态,重试合理。

### 不变量遵循(agent.md)

- #2 `--resolve` stdout 纯净:TTY 门控保证(resolve 在 `$(...)` 里非
  TTY,永不触发提示);所有提示/结果消息走 stderr。
- #5 bash/zsh wrapper 同步:不改 wrapper、不改 install.sh,零风险。
- 后端职责:写文件已有先例(`_save_names`),不碰 cwd,边界不变。

## 测试计划

`tests/test_cleanup.py`,stdlib `unittest`(项目零依赖哲学,Python
3.6+ 兼容),`python3 -m unittest discover tests` 运行。测试把
`SETTINGS_FILE`/`STATE_FILE` monkeypatch 到 `tempfile.mkdtemp()`,
**绝不触碰真实 `~/.claude`**。用例:

1. 检测:文件缺失 → `default`;`{}` → `default`;缺键 → `default`;
   键存在(任意值,含 3 天)→ `set`;非法 JSON → `unknown`。
2. 触发门控:三条条件各缺其一 → 不提示(`maybe_prompt_cleanup` 注入
   tty 标志与输入函数,断言无输出、marker 未写)。
3. 接受路径:y 输入 → settings.json 出现键且值 3650;marker =
   accepted;**其余行字节级不变**(前后逐行 diff,只有插入行不同)。
4. 拒绝路径:N/EOF → settings.json 字节级完全不变;marker = declined。
5. 非法 JSON:拒绝修改、文件字节不变、不写 marker、stderr 有指引。
6. 备份:接受路径产生 `cs-bak-*` 且内容 == 修改前原文;预置 5 份
   旧备份再接受 → 仅保留最近 5 份(轮转)。
7. 原子写失败(monkeypatch `os.replace` 抛 OSError)→ 原文件完好、
   报错、无 marker。
8. `{}` 空对象:生成合法小对象,含键,可解析。
9. 回归:marker 已存在(accepted/declined 两种)→ 零输出零修改。
10. 追加 A(M1):settings.json 存在但不可读(chmod 000)→
    `cleanup_status() == "unknown"`,不提示、不修改。
11. 追加 B(M3):marker 文件为非法 JSON → 行为等同首次运行(会
    提示),接受后写入合法 marker。
12. 追加 C(第 3 步单行分支):`{"model":"sonnet"}` 单行有内容 →
    插入后合法、`cleanupPeriodDays` 为首键、原内容字节保留。

## 文档更新(随实现一起)

- `agent.md`(gitignored,本地维护):Testing 节补 unittest 命令;
  File manifest 加 `tests/`。
- `README.md`:功能说明一小节(首次运行会问一次,如何拒绝/恢复);
  **明示已设置过 `cleanupPeriodDays` 的机器上此功能永不触发**——它
  面向新机器/重装,避免用户困惑"为什么 cs 从来不问";备份文件
  说明(`cs-bak-*`,保留最近 5 份)。

## 范围外(明确不做)

- 手动子命令(`cs -k` 之类)——用户选择永不再问 + Claude 帮改,不加。
- 检测企业/项目级 settings 覆盖(managed-settings 优先级高于用户级,
  cs 改用户级即为 best-effort,不越权)。
- 改 shell wrapper / install.sh。
- 读-改-写窗口内的并发写竞态(如 Claude Code 同时改 settings.json)
  ——最后写者赢,不加锁;`os.replace` 已保证崩溃安全。
- 恢复已删除的会话(不可能,转录已物理删除)。
