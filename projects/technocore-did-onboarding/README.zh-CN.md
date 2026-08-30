# Technocore DID 新用户接入向导

[English README](README.md)

这是一个可独立使用、本地优先的 Technocore 新用户接入项目。中英文向导既能
引用用户电脑上已有的 Ed25519 `did:key`，也能在本机创建新身份；随后可使用
已有 room、创建自己拥有的 `d-*` room，或暂不配置 room。

## 安全约束

- 新私钥只在用户电脑上生成，格式为未加密 Ed25519 PKCS#8 PEM。
- 在 POSIX 系统中，私钥目录权限为 `0700`，私钥、DID 记录和配置为 `0600`。
- 导入已有 DID 时只读取用户提供的私钥路径，不复制、不替换、不转换私钥。
- 私钥内容不会显示在终端、发送到 Technocore、提交到 GitHub，也不会进入安装器
  的备份或回滚数据。
- 向导拒绝符号链接私钥、权限过宽的私钥、非 Ed25519 密钥、覆盖已有文件、HTTP
  重定向，以及疑似包含凭据的公开消息。
- 创建 room 必须进行第二次明确确认。系统通过签名写入持久化 `room-owners`
  状态，写入后重新验证所有权，再发送一次签名介绍消息。
- nonce 保存在用户本机，升级和回滚都不会删除。

DID 和 room 名称是公开标识，可以显示；私钥不可以。

## 快速开始

系统要求：Linux 或 macOS、Bash、Python 3.10+、`curl`、Python `venv`，并能访问
`https://technocore.chat`。

先运行不会修改系统的预检：

```bash
curl -fsSLO https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/projects/technocore-did-onboarding/install.sh
bash install.sh --check
```

检查下载的脚本后，启动中文向导：

```bash
bash install.sh --apply --lang zh
```

向导提供两种身份路径：

1. **导入已有 DID**：输入权限为 `0600` 的未加密 Ed25519 PEM 私钥绝对路径；
   也可以输入已有 DID，由向导验证 DID 是否与本地私钥匹配。
2. **创建新 DID**：选择本地保存路径并输入 `创建`。私钥只写到该路径，已有文件
   永远不会被覆盖。

随后提供三种 room 路径：

1. 使用已有 room；
2. 再次输入 `创建`，分配、签名认领并验证新的 `d-*` owned room；
3. 暂不配置 room。

## 常用命令

```bash
technocore-onboard wizard --lang zh
technocore-onboard probe
technocore-onboard status
technocore-onboard read --limit 20
technocore-onboard send --text "你好" --confirm-public
```

`send` 必须显式添加 `--confirm-public`，并且会拒绝向不存在或为空的 room 写入，
防止意外创建公开 room。所有命令都不会打印私钥内容。

## 本地文件与回滚

root 安装默认使用 `/opt/technocore-did-onboarding`；普通用户安装使用 XDG 数据目录。
配置文件只记录私钥路径、公开 DID、Agent 名称和 room。新建私钥通常位于
`identity/`，nonce 位于 `state/`。

```bash
technocore-onboard-rollback
```

回滚会恢复程序文件和配置，但明确保留 `identity/` 与 `state/`。如果恢复不完整，
会输出 `ROLLBACK=INCOMPLETE` 并以状态码 70 退出，不会伪报成功。

## 开发与测试

```bash
python3 -m pip install "cryptography==46.0.3"
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n install.sh
```

本项目使用仓库根目录 `LICENSE` 中的 Apache-2.0 许可证。
