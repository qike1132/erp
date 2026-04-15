ERP 系统 - 部署说明
========================

快速开始
==========
1. 双击运行 ERP_System.exe
2. 打开浏览器访问: http://127.0.0.1:5003
3. 默认管理员账号: admin / admin123

系统要求
==========
- Windows 10/11 (64位)
- 无需安装 Python

数据库配置
============
如需使用 MySQL 数据库，请编辑 .env 文件：

DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=erp_system

如使用 SQLite（默认），无需配置。

文件说明
========
ERP_System.exe          - 主程序
.env                      - 配置文件
templates/                  - 网页模板
static/                     - 静态资源

常见问题
========
Q: 程序启动失败？
A: 检查是否有其他程序占用 5003 端口

Q: 数据库连接失败？
A: 检查 .env 配置是否正确

Q: 杀毒软件误报？
A: 将程序添加到白名单

技术支持
========
详细文档请查看 EXE_PACKAGING_GUIDE.md
