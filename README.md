# Telegram Bot 聊天记录导出与HTML生成工具

## 项目简介

该项目包含两个主要功能：
1. 导出Telegram聊天记录并写入SQLite数据库。
2. 将保存到数据库中的聊天记录生成HTML文件，并通过简单的服务器进行浏览和搜索。

<img width="1148" height="707" alt="image" src="https://github.com/user-attachments/assets/a9228a08-dc01-4285-a663-1d1d1732c1d2" />
<img width="877" height="1251" alt="image" src="https://github.com/user-attachments/assets/712303e8-6fcc-4cf4-a21f-8096524e3a9d" />
<img width="959" height="286" alt="image" src="https://github.com/user-attachments/assets/bac5e773-ade3-417d-9255-aa5704873aeb" />


## 文件说明

- `update_messages.py`：负责导出Telegram聊天记录。
- `main.py`：解析消息并写入数据库，同时生成 HTML 文件所需的数据。
- `server.py`：从数据库中按需加载聊天记录并支持搜索。
- `migrate_messages.py`：将旧版 `messages.json` 数据迁移到数据库。

## 使用方法

### 环境准备

1. 确保已安装Python 3.x。
2. 安装所需的Python库：
    ```bash
    pip install pillow
    ```
3. 安装[tdl](https://github.com/iyear/tdl)工具：
    
4. 使用`tdl login`进行登录：
    ```bash
    tdl login -T qr
    ```

### 迁移旧版 JSON 数据

若之前的版本生成过 `messages.json` 文件，可以使用以下脚本将其迁移到数据库：
```bash
python migrate_messages.py <user_id>
```

### 启动服务器查看聊天记录

导出并生成 HTML 后，可以启动内置服务器：
```bash
BOT_PASSWORD=你的密码 python server.py
```
服务器默认只监听本机的 `127.0.0.1`，并启用基本认证。访问
`http://localhost:5000/chat/<user_id>` 时浏览器会询问用户名和密码，默
认用户名为 `user`，密码由 `BOT_PASSWORD` 环境变量指定。
启动服务器后，也可以访问根地址 `/`，在网页表单中填写聊天 ID、备注，并选择是否下载文件、导出全部消息及原始数据来新增聊天记录。这些设置会保存到 `chats.json`，重启后仍会生效。服务器启动时会自动读取 `chats.json`，并为其中的每个聊天启动后台导出线程。

静态文件会从根路径提供，例如 `http://localhost:5000/resources/bg.png`、
`http://localhost:5000/fonts/Roboto-Regular.ttf` 和 `/downloads/<user_id>/...`。

## 注意事项

- 确保你有权限访问Telegram聊天记录。
