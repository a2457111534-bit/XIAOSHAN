# 小删 — 本地离线语音输入法（macOS / Windows）

当前版本：v2.3（macOS / Windows 双平台）

按住一个键连续说话，文字实时打进任何 App 的光标处（Word、WPS、微信、浏览器都行）；
说错了不用碰键盘——「小删除，删除上一句」嘴上改。

A local, offline voice-typing tool for macOS & Windows: hold one key and talk,
text lands at your cursor in any app — and edit by voice (“delete last sentence”).

完全本地离线识别（SenseVoice 模型），免费、不联网、内容不出电脑。

## 下载安装包（免配置，模型内置）

到 [Releases](../../releases) 页下载对应平台的压缩包，解压即用：

- **macOS（Apple 芯片）**：解压后右键 `XiaoShanMac` →「打开」放行（包未做开发者签名），
  按弹窗指引在系统设置勾选辅助功能与麦克风，之后正常双击运行
- **Windows**：解压后运行 `XiaoShan\XiaoShan.exe`，说话键等都在设置窗口里改

想自己从源码打包：mac 运行 `.venv/bin/pyinstaller XiaoShanMac.spec`；
Windows 双击 `build_win.bat`（产物在 `dist\`，模型自动装入）。

## 特性

- **按住说话，边说边出字**：说完一句停顿半秒，那句自动落进输入框；悬浮条实时显示草稿
- **语音编辑全家桶**：删除（按句/按字/按词/按标点，支持序数定位、批量删除、删N处）、替换、插入、撤销，20+ 条命令动嘴改
- **同音容错**：识别成“小山除，山除上一局”照样删对（拼音匹配兜底）
- **删得准、不误删**：删除/替换走“原子写入”（macOS 辅助功能 API / Windows UI Automation），
  整框设值、零退格序列；执行前先读输入框真实内容对齐账本，删完复核
- 命令成功只轻“叮”一声，失败才语音提示；ESC 随时作废本轮

## 安装（macOS）

需要 Python 3.10+。

```bash
git clone <本仓库> && cd voice-typist
./download_model.sh     # 下载离线模型（约240MB，只需一次；已下载会跳过）
./run.sh                # 首次运行自动建虚拟环境装依赖，然后启动
```

**权限（关键，各需手动勾选一次）**：
- 系统设置 → 隐私与安全性 → **辅助功能**：勾选运行程序的宿主（如“终端”）
- 系统设置 → 隐私与安全性 → **麦克风**：同上
- 勾选后重启小删。检查是否就绪：`.venv/bin/python run.py --selftest perms`

**使用**：光标放到任意输入框 → **按住 ⌘ 键（Win键盘=任意田字旗标键）连续说话**。
每说完一句稍微停顿，那句文字就落下来；要改就说「小删除，删除上一句」。

> 为什么不用 Option 键：豆包输入法等常把 Option 占作自己的语音热键，会互相打架。
> ⌘ 键不合适可在 config.json 里换 right_cmd / any_alt / f5 / f6，或在菜单“更改说话键”。

## 安装（Windows）

需要 Windows 10 1803+、Python 3.10~3.12（[python.org](https://www.python.org/downloads/) 安装时勾选 pip）。

```bat
git clone <本仓库> && cd voice-typist
download_model.bat                      :: 下载离线模型（约240MB，只需一次）
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements-win.txt
.venv\Scripts\python run_win.py --selftest mic
run_win.bat                             :: 启动（控制台常驻，Ctrl+C 退出）
```

**使用**：光标放到任意输入框 → **按住 右Ctrl 键连续说话**。
Windows 不需要任何系统授权；改说话键：`python run_win.py --set-key`。

> Windows 版：命令解析、会话账本、识别断句与 macOS 版完全同源，引擎逻辑同一套
> 测试覆盖；自带图形界面（主窗口 + 托盘 + 设置窗口，保存即生效）。

## 语音命令全集

**指令词**（任一即可，均带同音容错）：
- 删除系：小删除 / 想删除 / 小山口 / 小山竹 / 小珊瑚 / 小山虫
- 替换系（兼管插入）：小替换 / 想替换 / 想退换 / 小退换
- 发送系：大宝贝 / 大宝贝儿（"大宝贝，发送"=按回车发送；发送是它俩的专线）
- 指令词后可带”请/帮我/给我/麻烦”；指令词单独成句会进入 4 秒待命，下一句自动接续为命令

**删除：**

| 说什么 | 效果 |
|---|---|
| 删除上一句 / 刚才那句 / 最后一句（说”小删除，删除”或”小删除，上一句”省略式也行） | 删最后一句 |
| 删除第三句 / 倒数第二句 / 最后两句 | 按句序删某句 / 删最后N句 |
| 删除第五个字 / 倒数第三个字 | 按字位删 |
| 删除”好”字 / 删掉你好 / 小删除你好 | 删某字词（它最后一次出现的地方） |
| 删除最后五个字 | 删最后 N 个字（中文数字都认） |
| 删除两个句号 / 三个好字 | 删最后 N 处 |
| 删除第一个句号 / 倒数第二个句号 / 最后一个问号 / 第一个”我” | 序数定位删 |
| 删除刚才那段 | 删掉最后一次口述的整段 |
| 删除含有”××”的那句话 | 按内容删句 |
| 删除问号 / 句号 / 逗号 / 顿号 / 分号 / 冒号 / 叹号 | 删最后一个该标点 |
| 删除标点 / 删除所有标点 | 删最后 / 全部标点 |
| 删除额和逗号 / 删除你好和问号（用顿号分隔多项，各项可带序数数量） | 批量删除 |
| 小删除全部 / 删除所有文字 | 清空全部 |
| 撤销 / 撤回 / 撤回上一句 / 收回刚才说的 / 反悔 / 恢复 | 撤回小删的上一步（整框原子写回，一步到位）/ 重做 |
| 大宝贝，发送 / 把它发出去 / 发吧 / 直接发送吧（发送是「大宝贝」专线；带儿化音「大宝贝儿」也认） | 按回车，把打好的内容发出去 |

**替换：**

| 说什么 | 效果 |
|---|---|
| 把A改成B / A改成B（”把”可省）/ A替换成B / A为B | 替换 |
| 问号改成句号 | 标点替换 |
| 倒数第二个句号为逗号 / 第一个问号改成句号 | 序数定位替换 |

**插入：**

| 说什么 | 效果 |
|---|---|
| 在你好后面加逗号 / 在你好前面加句号 | 锚点后 / 前插入 |
| 在你好和你是谁之间加逗号 | 两者之间插入 |
| 把逗号加在 / 放在你好后面 | 倒装插入 |
| 加个句号 / 最后打个句号 | 末尾追加 |
| 在你好后面加入我叫小明（内容可到 30 字） | 长内容插入 |
| 换行 / 另起一段 | 回车 / 空一行 |

**识别容错（三层）**：①指令词拼音匹配（识别成”小山除”照样触发）；②结构字容错（句→据/局、一→依/已、那→拿/哪）；③内容同音兜底（说”号”命中”好”，标点名”问好”自动理解为问号）。
不以指令词开头的一切话都正常上屏，包括含”删除”二字的句子；命令成功只轻”叮”一声，失败才语音提示，按 ESC 随时作废本轮。

## 工作原理（为什么删得准）

软件维护一份**会话缓冲区**，记住它自己打出去的每一个字。删除/替换时：

1. 先读输入框的**真实内容**，把缓冲区与实际对齐（跨启动残留、手动编辑都能消化）；
2. 有选中文字或光标不在末尾时**拒绝执行**并语音提示（防删错位置）；
3. 优先走**原子写入**：整框内容一次性设新值，零退格序列，物理上不可能误删
   （应用不支持时才回退“退格+粘贴”，并有 150 字跨度保险丝）；
4. 删完**复核**一次，账实不符会记日志并按实际重新对齐。

这个机制成立的前提：**光标一直停在口述内容的末尾**。
如果中途手动点了别处，删除/替换会拒绝执行或提示——把光标点回文末，或说「小删除，撤销」。
单次删除超过 3000 字会拒绝执行并提示手动处理（安全上限）。

## 配置（config.json）

| 键 | 默认 | 说明 |
|---|---|---|
| trigger_word | 小删除… | 指令词列表，可自定义 |
| hotkey | mac: any_cmd / win: right_ctrl | 说话热键；也可 `python run_win.py --set-key` 按键即存 |
| push_mode | hold | hold=按住说话；toggle=按一下开始再按结束 |
| tts_voice | zh-CN-XiaoyiNeural | mac 语音播报音色（可选安装 edge-tts 后生效，未装自动用系统语音）；Windows 用系统 SAPI 语音 |
| tts_feedback / sound_feedback | true | 语音报错 / 提示音 |
| model_dir / num_threads | — | 识别模型目录 / 推理线程数 |

改完配置重启小删生效。

## 开发

```bash
python tests/test_commands.py       # 命令解析测试（100+ 项）
python tests/test_engine.py         # mac 引擎逻辑测试（不真打字）
python tests/test_win_engine.py     # Windows 引擎逻辑测试（任何平台可跑）
python run.py --selftest asr tests/f2.wav   # 识别一个 wav（先 bash tests/make_fixtures.sh 造音频）
python run.py --selftest type 测试文字      # 3秒后打进当前光标处
python run_win.py --selftest uia   # Windows：读当前焦点文本框
```

目录：`voice_typist/` macOS 版源码（asr 识别 / audio 录音断句 / inject 键盘注入 /
session 会话缓冲 / commands 命令解析 / engine 执行 / app 菜单栏主程序），
`voice_typist_win/` Windows 版（win_engine 与 mac 版逐行对应，注入/UIA/TTS/悬浮条为平台实现），
`tests/` 测试，`ime/` 真·输入法（IMKit）实验性路线（未接线）。

## 已知边界

- 识别引擎对中文普通话效果最好；语速自然、环境安静时准确率高。
- “小删除”三个字真的想上屏：换个 trigger_word。
- 撤销命令假定目标 App 的 Cmd/Ctrl+Z 撤销的是小删的上一步操作；如果你在中间手动
  打过字，两者会错位——先手动撤销对齐，或直接停用语音撤销。
- Windows：向**管理员权限**运行的窗口注入会被系统拒绝（保持小删与目标程序同为普通权限即可）。
- 模型目录里 model.onnx（约900MB）是全精度版备用，实际用 model.int8.onnx，
  磁盘紧张可删掉前者。

## 第三方组件与致谢

本项目站在以下开源组件之上（经 pip 安装使用，不随本仓库捆绑分发）：

| 组件 | 用途 | 许可证 |
|---|---|---|
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | 推理运行时 | Apache-2.0 |
| [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)（Alibaba FunAudioLLM） | 语音识别模型 | 代码 MIT；模型权重遵循 [FunASR 模型开源许可证](https://github.com/FunAudioLLM/SenseVoice)（允许商用，需保留版权声明与模型名） |
| [silero-vad](https://github.com/snakers4/silero-vad) | 语音活动检测断句 | MIT |
| [pynput](https://github.com/moses-palmer/pynput) | 全局热键 | LGPL-3.0 |
| pypinyin / sounddevice / numpy / pyobjc / rumps | 拼音匹配 / 录音 / 数值 / 系统桥接 / 菜单栏 | MIT / MIT / BSD-3 / MIT / BSD-3 |
| [uiautomation](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) / comtypes（Windows） | 焦点文本框读写 | Apache-2.0 / MIT |
| pystray / pillow（Windows） | 托盘图标与设置界面 | LGPL-3.0 / MIT-CMU |

模型文件不在本仓库内，由 `download_model` 脚本从上游官方 release 直接下载；
模型权利归原作者所有，按其许可证使用。

可选组件：`pip install edge-tts` 可启用更好听的微软神经语音播报
（[edge-tts](https://github.com/rany2/edge-tts) 为 GPL-3.0，属用户自行安装的可选组件，本项目不分发它；未安装时自动使用系统语音）。

## 许可证

本项目自身代码以 [MIT](LICENSE) 发布。

## 作者

文祥、赵娜
