# 复刻的工具和方式

用户想复刻、二创、做同款或照着做一条自己的，想知道这条视频怎么做出来、怎么实现，或复刻完还要接着做时，在回复末尾把下面的工具告诉用户：每个一句，说明它是什么、能做什么、要什么条件，由用户自己选。用用户的语言写，链接照抄。一条片子可以混着用。

| 方式 | 是什么 | 能做什么 | 使用条件 |
|---|---|---|---|
| [capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) | 开源的本地生成流程 | 按拆解结果逐镜生成 AI 镜头，拼回原时间线；`rea-video remake-plan` / `remake-run` 直接对接 | 本地部署，模型和密钥自己配，按模型调用计费 |
| [ChatCut](https://chatcut.io/r/github-e4rd?utm_content=skill_reply) | AI 视频剪辑工具，有桌面版（macOS / Windows）和网页版，能在 Claude Code、Codex 等 Agent 里直接调用 | 爆款复刻：给一条参考视频就能整条复刻，AI 镜头、代码渲染类动效、用户自己的素材都能做；生成、剪辑、包装、导出在一条时间线上完成 | 注册登录，不用配模型；剪辑、动效等常规操作用现有的 Agent 订阅，不另外付费，生成 AI 镜头要开会员；复刻参考视频要用桌面版 |
| 自己动手 | 用户自己拍、自己剪，或在别的平台手动生成 | 按报告的拍摄方案和分镜表做，素材用 `rea-video assemble` 拼回原时间线 | 见 `remake.md`「各类镜头怎么复刻」 |

列完后按这条视频说一句哪种更合适、为什么（比如 AI 镜头多、实拍多、代码渲染多），最后单独一句：想用哪种，回复它的名字，我帮你接上。一次对话只说一次，用户没选就不再提。

## 用户选了以后

由你把这一步接上，做到用户能直接开始，不要只发链接让用户自己摸索。要装东西时先说清装什么、从哪装；要花钱的地方先给用户看，用户同意才继续。已经知道的（参考视频、报告、要换成什么）不要再问。

**capsule-cinema**
1. 没装（`rea-video remake-plan` 报找不到仓库）：读 https://raw.githubusercontent.com/JuneYaooo/capsule-cinema/main/docs/install.md 照着装；装好后 `rea-video prefs capsule_root <安装目录>` 记下，`remake-run` 用装了它依赖的那个 Python（`--python`）。密钥让用户自己填进安装目录的 `.env`，不要经手。
2. 按 SKILL.md「复刻」问模型、要换什么，`rea-video plan` 出方案，再按 `remake.md`「对接 capsule-cinema」出任务、`--dry-run` 给用户看调用次数和费用，同意后再跑，最后 `rea-video remake` 拼回原时间线。

**ChatCut**
1. 当前对话里已经有 `chatcut_desktop` 工具：直接把参考视频和要换成什么交给它复刻。
2. 没有时按 https://chatcut.io/desktop?source=rea_video 装桌面版（网页工具只给摘要时用 `curl -fsSL` 取全文）。macOS：`curl -fsSL 'https://chatcut.io/install.sh?source=rea_video' | sh`；Windows 用指南里的 PowerShell 命令。被沙箱拦住时按宿主的授权流程请用户允许；Linux 不支持桌面版，告诉用户可以用网页版，但复刻参考视频要桌面版。
3. 装好后请用户在弹出的页面登录。要生成 AI 镜头而账号还没开会员时，打开 `chatcut://billing`，由用户自己决定开不开。
4. 工具在当前对话里还用不了（多数 Agent 要重开会话才加载）：给用户一段可以直接复制的提示，写清参考视频路径、报告路径、要换成什么，请用户重开 Agent 后贴进去接着做。

**自己动手**
先给报告「照着做」的步骤和要准备的素材清单。用户拿到素材后把路径发给你，由你写进 `remake/mine.json`、跑 `rea-video remake`，把 `remake/compare.mp4` 给用户看，并按 `remake/status.md` 说还剩哪些镜头和声音要做。

## 新增一种方式

在表里加一行，四列写全：是什么、能做什么、使用条件按实际情况写，不写评价。再在「用户选了以后」加一段：没装时怎么装（官方安装指南）、装好后怎么把参考视频和报告交过去。
