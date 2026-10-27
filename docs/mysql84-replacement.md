# 本地 MySQL 8.4 测试实例替换记录

日期：2026-10-26。用户在M1补全期间明确确认“本地都是测试数据，直接替换”，授权范围覆盖了原先不更改本地MySQL服务的限制。执行仅替换本地测试服务，不删除旧安装和数据目录，不更改根目录.env。

## 实际结果

| 项目 | 结果 |
| --- | --- |
| 新服务 | MySQL84_ESC，Automatic，端口3306 |
| 实际Server版本 | MySQL Community Server 8.4.13，Win64/x86_64 |
| 存储引擎 | InnoDB |
| 新安装 | C:\MySQL\MySQL Server 8.4 |
| 新数据目录 | C:\MySQL\MySQL Server 8.4\Data |
| 旧服务 | MySQL80，Stopped，Manual |
| 旧安装/数据 | C:\MySQL\MySQL Server 8.0及其Data目录保留 |
| 根.env | 沿用原连接端口及凭据，助手未修改 |

这是**新建8.4实例并切换服务**，不是把8.0.26的数据文件直接交给8.4。旧实例的52张表没有迁入新实例，仍保留在旧数据目录；新实例的项目库只建立M1认证基础表。

## 安装与校验

使用Oracle官方下载页所列8.4 LTS Windows ZIP，版本8.4.13，未安装第三方数据库替代品。[官方下载](https://dev.mysql.com/downloads/mysql/8.4.html)

- 包：mysql-8.4.13-winx64.zip。
- 官方公布MD5：`7b94489d5524dea9b27097068bea25a8`，实测一致；此处记录的是包完整性校验，不声称完成PGP签名验证。
- 实测SHA256：`e9cd98b1d23f122987b1afca26ad942efec5891481103d48ae3cde237fa3ea54`。
- 在全新目录初始化，临时回环端口验证版本/路径/引擎后，通过数据库协议设置原.env中的root凭据；密码未置于命令行或日志。
- Windows服务注册及切换经UAC批准；切换脚本含验证失败恢复旧服务的逻辑；实际切换退出0。
- 新服务只绑定回环地址，关闭MySQL X端口，避免与旧服务其他端口冲突。

Windows服务切换需要操作系统管理员权限，数据库root权限不能代替它。[官方服务说明](https://dev.mysql.com/doc/refman/8.4/en/windows-start-service.html)

## 验收证据

本机忽略目录`.local/mysql84/`保留：

- `prepared.json`：安装包hash、实际版本、独立数据目录和.env基线hash。
- `cutover-result.json`、`post-cutover-check.log`：服务切换及实际Server核验PASS。
- `restart-result.json`、`restart-check.log`、`persistence.json`：新服务重启PASS，13条合成测试用户记录保留，.env哈希不变，旧数据目录仍存在。
- `mysql84-validation.json`、`mysql84-migration.log`、`mysql84-pytest.log`、`mysql84-model-check.log`：独立库`esc_m1_test_84_f452dc12f3`、专用账号`esc_m1_84_f452dc12f3`，迁移版本0001_auth，28项测试通过，所有基础表为InnoDB，Alembic模型检查无新增操作。
- `mysql84-test.env`是独立测试凭据文件，被Git忽略，不作为公开报告附件。

新实例项目库另外执行`alembic upgrade head`和`alembic check`，成功。没有创建CRM业务表或默认管理员；需要登录时按README交互式创建开发账号。

## 使用与回退

服务器版本以`SELECT VERSION()`为准。系统PATH未改，原`mysql`命令可能仍指向8.0客户端；8.4工具位于`C:\MySQL\MySQL Server 8.4\bin`，使用完整路径即可。客户端版本显示不代表当前3306服务器版本。

本轮替换后，旧`.local/native.env`仍引用旧服务中的独立开发库；不要用它判断新实例是否就绪。当前应用使用根目录.env连接新服务，具体启动步骤见README。

需要回到旧测试数据时，在管理员PowerShell中执行以下人工回退步骤；本次没有执行回退：

```powershell
Stop-Service MySQL84_ESC
Set-Service MySQL84_ESC -StartupType Manual
Set-Service MySQL80 -StartupType Automatic
Start-Service MySQL80
```

回退后3306重新指向旧8.0实例，新8.4的数据仍留在新目录。不要删除任一数据目录，不要用旧二进制打开8.4的数据文件。M1完整验收结果另见[m1-report.md](m1-report.md)。
