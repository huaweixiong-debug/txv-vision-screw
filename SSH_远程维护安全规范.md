# SSH 远程维护安全规范

本文档用于约束 Codex、Claude Code 或其他自动化代理在操作服务器 SSH 配置时的行为，目标是避免再次出现：

```text
bash: line 1: /etc/ssh/force_command.sh: Permission denied
Connection closed.
```

## 核心原则

1. 不要让 SSH 登录依赖一个没有验证过的外部脚本。
2. 修改 SSH 配置前必须备份。
3. 修改 SSH 配置后必须执行 `sshd -t`。
4. 不要关闭当前可用会话，必须先用新窗口测试 SSH 成功。
5. 禁止一次性粘贴需要交互输入 sudo 密码的长命令。
6. Telnet 只能作为临时救援入口，SSH 恢复后应关闭或限制 Telnet。

## 禁止事项

自动化代理不得直接执行以下高风险操作：

```sh
sudo sed -i '/ForceCommand/d' /etc/ssh/sshd_config
sudo systemctl restart sshd
sudo rm -f /etc/ssh/force_command.sh
sudo chmod -R 777 /etc/ssh
```

原因：

- 直接删除 `ForceCommand` 行可能破坏 `Match` 块语义。
- `restart sshd` 比 `reload sshd` 风险更高。
- 删除 `force_command.sh` 会导致配置仍引用脚本时 SSH 直接断开。
- 递归放宽 `/etc/ssh` 权限会带来安全风险。

## SSH 配置修改标准流程

### 1. 保持当前会话

在修改 SSH 前，必须保留当前可用登录窗口，不要退出。

如果当前 SSH 已不可用，应优先使用以下方式进入服务器：

```powershell
telnet 服务器IP 23
```

注意：Telnet 不支持 `用户名@IP` 写法。登录后再输入用户名和密码。

### 2. 先刷新 sudo 凭据

不要直接粘贴长命令。先执行：

```sh
sudo -v
```

如果提示密码，手动输入密码。确认返回 shell 提示符后，再继续执行后续命令。

### 3. 备份 SSH 配置

```sh
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%F-%H%M%S)
sudo find /etc/ssh/sshd_config.d -type f -name '*.conf' -exec cp {} {}.bak.$(date +%F-%H%M%S) \; 2>/dev/null
```

### 4. 检查 ForceCommand

```sh
sudo grep -RIn "^[[:space:]]*ForceCommand\|^[[:space:]]*Match" /etc/ssh/sshd_config /etc/ssh/sshd_config.d 2>/dev/null
```

如果发现：

```text
ForceCommand /etc/ssh/force_command.sh
```

必须确认脚本存在、可执行、属于 root。

### 5. 修复 force_command.sh 权限

```sh
sudo chown root:root /etc/ssh/force_command.sh
sudo chmod 755 /etc/ssh
sudo chmod 755 /etc/ssh/force_command.sh
sudo sed -i 's/\r$//' /etc/ssh/force_command.sh
```

验证：

```sh
ls -ld /etc/ssh /etc/ssh/force_command.sh
```

期望结果：

```text
drwxr-xr-x ... /etc/ssh
-rwxr-xr-x ... /etc/ssh/force_command.sh
```

### 6. 如果不需要 ForceCommand，优先禁用

不要删除配置行，使用注释方式禁用：

```sh
sudo sed -i -E 's/^([[:space:]]*)ForceCommand[[:space:]]+\/etc\/ssh\/force_command\.sh/# disabled: ForceCommand \/etc\/ssh\/force_command.sh/I' /etc/ssh/sshd_config
sudo find /etc/ssh/sshd_config.d -type f -name '*.conf' -exec sed -i -E 's/^([[:space:]]*)ForceCommand[[:space:]]+\/etc\/ssh\/force_command\.sh/# disabled: ForceCommand \/etc\/ssh\/force_command.sh/I' {} \; 2>/dev/null
```

### 7. 校验 SSH 配置

```sh
sudo sshd -t
```

如果没有输出，通常表示配置语法通过。

查看当前用户最终生效配置：

```sh
sudo sshd -T -C user=$(whoami),host=$(hostname),addr=127.0.0.1 | grep -i forcecommand
```

期望之一：

```text
forcecommand none
```

或者脚本确实可执行时：

```text
forcecommand /etc/ssh/force_command.sh
```

### 8. 重载 SSH

优先 reload，不要 restart：

```sh
sudo systemctl reload sshd 2>/dev/null || sudo systemctl reload ssh 2>/dev/null || sudo service sshd reload 2>/dev/null || sudo service ssh reload
```

### 9. 新窗口测试

在本机新开 PowerShell 窗口测试：

```powershell
ssh 用户名@服务器IP
```

确认新 SSH 成功登录后，才允许关闭旧会话。

## 建议的 force_command.sh 内容

如果确实需要保留 `/etc/ssh/force_command.sh`，建议内容如下：

```sh
#!/bin/sh

if [ -n "$SSH_ORIGINAL_COMMAND" ]; then
    exec /bin/sh -c "$SSH_ORIGINAL_COMMAND"
fi

if [ -x /bin/bash ]; then
    exec /bin/bash -l
fi

exec /bin/sh
```

部署命令：

```sh
sudo tee /etc/ssh/force_command.sh >/dev/null <<'EOF'
#!/bin/sh

if [ -n "$SSH_ORIGINAL_COMMAND" ]; then
    exec /bin/sh -c "$SSH_ORIGINAL_COMMAND"
fi

if [ -x /bin/bash ]; then
    exec /bin/bash -l
fi

exec /bin/sh
EOF

sudo chown root:root /etc/ssh/force_command.sh
sudo chmod 755 /etc/ssh/force_command.sh
sudo sed -i 's/\r$//' /etc/ssh/force_command.sh
sudo sshd -t
```

## 故障恢复

### 报错：No such file or directory

```text
bash: line 1: /etc/ssh/force_command.sh: No such file or directory
```

说明 `sshd_config` 引用了脚本，但脚本不存在。

处理方式：

1. 通过 Telnet 或本地控制台登录。
2. 补回 `/etc/ssh/force_command.sh`。
3. 或注释掉 `ForceCommand /etc/ssh/force_command.sh`。
4. 执行 `sudo sshd -t`。
5. reload SSH。

### 报错：Permission denied

```text
bash: line 1: /etc/ssh/force_command.sh: Permission denied
```

说明脚本存在，但不能执行。

处理方式：

```sh
sudo chown root:root /etc/ssh/force_command.sh
sudo chmod 755 /etc/ssh
sudo chmod 755 /etc/ssh/force_command.sh
sudo sed -i 's/\r$//' /etc/ssh/force_command.sh
sudo sshd -t && sudo systemctl reload sshd
```

### 报错：Permission denied, please try again

```text
Permission denied, please try again.
```

这通常只是 SSH 密码错误、账号错误、认证方式不匹配，和 `ForceCommand` 不一定有关。

如果密码通过后才出现 `force_command.sh` 报错，则说明认证成功，但会话启动失败。

## 给 Codex / Claude Code 的执行要求

自动化代理在处理 SSH 问题时必须遵守：

1. 先判断当前错误属于认证失败、脚本缺失、脚本权限错误，还是 SSH 配置语法错误。
2. 如果 SSH 登录阶段已经断开，不得反复尝试用 SSH 修复 SSH，必须改用 Telnet、本地控制台、云厂商控制台或已有会话。
3. 需要 sudo 密码时，先执行 `sudo -v`，等待用户手动输入密码成功后，再粘贴长命令。
4. 所有 SSH 配置修改必须先备份。
5. 所有 SSH 配置修改必须执行 `sshd -t`。
6. 所有服务变更优先使用 reload。
7. 必须要求用户在新窗口验证 SSH 成功后，才关闭救援会话。
8. 不允许递归修改 `/etc/ssh` 权限。
9. 不允许删除未知用途的 SSH 配置行，只能注释并保留原内容。
10. 恢复成功后，应建议关闭 Telnet 或限制 Telnet 访问来源。

## 推荐最终状态

如果没有明确业务需求，推荐最终状态是：

```text
forcecommand none
```

如果必须使用 `ForceCommand`，推荐仅对指定用户启用：

```sshconfig
Match User some_user
    ForceCommand /etc/ssh/force_command.sh
```

并确保：

```text
/etc/ssh/force_command.sh 属于 root:root
/etc/ssh/force_command.sh 权限为 755
/etc/ssh 权限为 755
```

## 修复后关闭 Telnet

确认 SSH 可用后，建议关闭 Telnet：

```sh
sudo systemctl disable --now telnet 2>/dev/null || true
sudo systemctl disable --now xinetd 2>/dev/null || true
```

如果设备必须保留 Telnet 作为救援入口，应至少限制来源 IP，并记录启用原因。
