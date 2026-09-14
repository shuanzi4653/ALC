# Windows PowerShell 5.1 启动兼容性修复

用户报错中的斜杠运算符、缺少引号、缺少大括号等，是脚本编码误读引起的连锁解析失败，并非多处业务逻辑同时损坏。

## 根因

`start.bat` 使用系统的 Windows PowerShell 5.1。包含中文的 `dev.ps1` 使用无BOM的UTF-8，5.1按系统ANSI编码读取后产生乱码及解析错误。先前在较新PowerShell中的验证没有覆盖实际启动器使用的解释器。

原生5.1复现发现：dev.ps1有11项解析错误，backup.ps1有2项，restore-backup.ps1有4项。

## 修复

- 三个受影响脚本改为UTF-8 BOM，保留原业务逻辑。
- 添加 `.editorconfig`，要求PowerShell文件采用UTF-8 BOM。
- 新增 `scripts/check-powershell.ps1`，用实际解释器检查8个脚本的编码与语法；启动器先运行预检，避免再次输出成片解析错误。
- dev.ps1逐个核对JDK release版本，只接受17/21。系统JAVA_HOME当前指向26时，自动选择本机17；不改系统环境变量。
- Vite脚本路径加引号，兼容项目路径含空格的情况。

## 验证

- Windows PowerShell 5.1.26100.9444：8个脚本全部通过。
- 通过5.1实际执行完整源码编译与启动，Maven BUILD SUCCESS；Python、Java和Vite服务均就绪。
- 通过5.1实际停止本次受管三个进程，退出码0；再启动成功。
- 最终启动选择Microsoft JDK17.0.19，未再出现JDK26导致的Maven兼容性警告。

未执行备份恢复写入或发布构建；没有上传、打包或覆盖旧JAR。最终保留本地服务运行，页面为 http://127.0.0.1:5180 。

以后可单独运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/check-powershell.ps1
```
