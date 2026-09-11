---
name: github-push-windows
description: Windows 下向 GitHub 推送的完整三件套流程（坑 23/25/26 的配套解法）。触发场景：git push 失败、push 无输出但退出码 0、Empty reply from server、CONNECT 502、remote-https is not a git command、远端不更新、refs 引用缺失。
agent_created: true
---

# Windows 下 GitHub push 三件套

在 WorkBuddy（PortableGit）环境下向 GitHub 推送的完整流程。三个坑叠加，缺一不可，按顺序执行。

## 前置判断

先确认是否真的需要 push（节省 token）：
```bash
git status --short                     # 有无变更
git rev-parse HEAD                     # 本地 HEAD
git ls-remote origin main              # 远端实际哈希（直连查询，不依赖本地 refs）
```

## 三件套（顺序执行）

### ① 坑 26：PortableGit exec-path 缺 git-remote-https

- 现象：`git push` 无任何输出且 EXIT=0、远端不更新；显式报 `git: 'remote-https' is not a git command`。`ls-remote` 正常。
- 根因：WorkBuddy 自带 PortableGit（`~/.workbuddy/binaries/PortableGit/versions/<ver>/`），`git --exec-path` 指向 `mingw64/libexec/git-core`，该目录缺 helper（实际在 `mingw64/bin/`）。
- 解法：push 前设置 exec-path（PowerShell/bash 通用）：

```bash
PG="$HOME/.workbuddy/binaries/PortableGit/versions/1.2.0"
GIT_EXEC_PATH="$PG/mingw64/bin" "$PG/mingw64/bin/git.exe" -c http.proxy=http://127.0.0.1:7897 push origin main
```

### ② 坑 25：沙箱代理拦截 github.com git 端点

> ✅ **2026-09-11 实测修正：坑 25 并不必然出现，不要一上来就启 Clash。**
> 当日环境变量代理是 `http://127.0.0.1:49282`，**直接 `git push origin main` 就成功**（输出 `60bd02a..c8c9a2a  main -> main`、EXIT=0，非静默）。同日 Clash 未启动、7897 未监听，走 7897 反而报 `Failed to connect to github.com:443 over proxy 127.0.0.1 after 2093 ms`。
> ⇒ **正确顺序：先直接 push；只有出现下列症状才切 Clash。**
>
> ⚠️ **同一会话内 502 会反复出现（19:20 实测）**：同一条命令在 19:1x–19:2x 连推两次均成功（`c8c9a2a`、`f46c114`），约 10 分钟后**同一代理改为稳定返回 `CONNECT tunnel failed, response 502`**（重试 2 次均是 EXIT=128）；改用 `-c http.proxy=` 强制直连则报 `Failed to connect to github.com:443 after 21057 ms`（无梯子时直连必失败）。
> ⇒ **502 多为暂态：先重试 1–2 次；仍失败再启 Clash Verge（需启动 GUI，混合端口 7897），或稍后重试。** 不要把 502 当成永久故障。

- 现象：`Empty reply from server` / `CONNECT tunnel failed, response 502`；api.github.com 经同一代理返回 200。
- 根因：环境变量 `http_proxy=127.0.0.1:50580` 是 WorkBuddy 沙箱代理（sandbox-cli.exe），放行 api.github.com 但拦截 github.com 的 git-receive-pack。
- 解法：启动 Clash Verge（`C:\Program Files\Clash Verge\clash-verge.exe`，混合端口 7897；端口未监听时先启动 GUI），**用 `-c http.proxy` 显式覆盖即可，无需清环境变量**：

```bash
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main
```

> ⚠️ 注意：`env -u http_proxy ...` 清变量方式**单独用可行**，但若与 `GIT_EXEC_PATH` 组合使用会**静默失败**（无输出且远端不更新）。推荐统一用 `-c http.proxy` 显式覆盖。

### ③ 坑 23：PortableGit 写不了 refs/remotes

- 现象：push 成功后 `git status` 仍显示 ahead（本地分支领先远端），refs 引用缺失/过期；**另一种报法是 `Your branch is based on 'origin/main', but the upstream is gone.`（2026-09-11 实测命中的变体）**。两种都是 refs 缺失，解法相同。
- 根因：PortableGit 写 `refs/remotes/` 静默失败；`git update-ref` 同样失效；短哈希不认。
- 解法：手动写引用文件，必须**完整 40 位哈希**：

```bash
mkdir -p .git/refs/remotes/origin && printf '%s\n' "$(git rev-parse HEAD)" > .git/refs/remotes/origin/main
```

> ⚠️ **2026-09-11 补充实测（重要）**：
> - **`git fetch origin` 绕不过**：本次 fetch 报 `* [new branch]  main  -> origin/main`、EXIT=0，但 `refs/remotes/origin/main` **依然不存在** —— fetch 与 push 一样静默不落地。
> - **必须分两步、逐步复验**：先建目录（PowerShell：`New-Item -ItemType Directory -Path "$repo\.git\refs\remotes\origin" -Force`），**确认目录存在**后再写文件。父目录不存在时 `[IO.File]::WriteAllText` 会**静默不落地**（不抛错到输出流），只写文件不建目录＝白干。
> - **见效判据**：`git status -sb` 首行由 `## main...origin/main [gone]` 变为 `## main...origin/main`。

## 完整命令模板（一次成型）

```bash
cd <repo>
PG="$HOME/.workbuddy/binaries/PortableGit/versions/1.2.0"
export GIT_EXEC_PATH="$PG/mingw64/bin"
GIT="$PG/mingw64/bin/git.exe"

# ① 先直接 push（2026-09-11 实测多数情况可用，不要一上来就启 Clash）
"$GIT" push origin main

# ② 仅当 ① 报 Empty reply / 502 时，才切 Clash（需先启动 Clash Verge GUI，混合端口 7897）
"$GIT" -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main

# ③ 补 refs（坑 23 几乎必现，push 成功也要做）
mkdir -p .git/refs/remotes/origin && printf '%s\n' "$(git rev-parse HEAD)" > .git/refs/remotes/origin/main

# ④ 验证
git status | head -3        # 期望 up to date with 'origin/main'
git ls-remote origin main   # 期望 = git rev-parse HEAD
```

> ⚠️ **Windows/PowerShell 注意**：`$HOME` 在 PowerShell 中不展开，须用 `$env:USERPROFILE`；分步调用时用 `git -C <repo>` 代替 `cd`，并先 `$env:GIT_EXEC_PATH="<PG>\mingw64\bin"`。
> ⚠️ **提交信息含中文时**：用 `-F <文件>` 传消息，文件以 **UTF-8 无 BOM** 写入（`[System.IO.File]::WriteAllText($p,$msg,(New-Object System.Text.UTF8Encoding($false)))`），否则 git 收到的消息会乱码。

## 验证标准

- push 输出 `旧哈希..新哈希 main -> main`（不是静默）
- `git ls-remote origin main` = `git rev-parse HEAD`
- `git status` 显示 `up to date with 'origin/main'`

## 备用方案

- 无 Clash / 节点失效：手机热点或换网络后直连（清代理环境变量）
- 系统 Git（非 PortableGit）无坑 23/26，仅需处理代理
