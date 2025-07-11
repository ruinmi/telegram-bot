# Telegram Bot 聊天记录导出与HTML生成工具

## 项目简介

该项目包含两个主要功能：
1. 导出Telegram聊天记录并写入SQLite数据库。
2. 将保存到数据库中的聊天记录生成HTML文件，并通过简单的服务器进行浏览和搜索。

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

### 导出聊天记录并生成HTML文件

运行以下命令导出聊天记录并生成HTML文件：
```bash
python main.py <user_id> [--remark 昵称]
```
其中，`<user_id>`是你要生成HTML文件的用户ID，`--remark` 可为该聊天设置备注名。

如果你已经导出过聊天记录，可以使用`--ne`选项跳过导出步骤：
```bash
python main.py <user_id> --ne
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

静态文件会从根路径提供，例如 `http://localhost:5000/resources/bg.png`、
`http://localhost:5000/fonts/Roboto-Regular.ttf` 和 `/downloads/<user_id>/...`。

## 日志文件

导出聊天记录的日志会保存在`update_messages.log`文件中，方便排查问题。

## 注意事项

- 确保你有权限访问Telegram聊天记录。
- 聊天记录会存储在`data/<user_id>/messages.db`数据库文件中，生成的HTML文件也会保存在当前目录。
- 如果使用`--remark`设置备注名，相关信息会保存在`data/<user_id>/info.json`。
