# Telegram Bot 聊天记录导出与HTML生成工具

## 项目简介

该项目包含两个主要功能：
1. 导出Telegram聊天记录并保存为JSON文件。
2. 将导出的聊天记录生成HTML文件，并通过简单的服务器进行浏览和搜索。

## 文件说明

- `update_messages.py`：负责导出Telegram聊天记录并保存为JSON文件。
- `main.py`：解析消息并生成 HTML 文件。
- `server.py`：提供接口按需加载聊天记录并支持搜索。

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
python main.py <user_id>
```
其中，`<user_id>`是你要生成HTML文件的用户ID。

如果你已经导出过聊天记录，可以使用`--ne`选项跳过导出步骤：
```bash
python main.py <user_id> --ne
```

### 启动服务器查看聊天记录

导出并生成 HTML 后，可以启动内置服务器：
```bash
python server.py
```
然后在浏览器中访问 `http://localhost:5000/chat/<user_id>` 查看聊天记录。

静态文件会从根路径提供，例如 `http://localhost:5000/resources/bg.png`、
`http://localhost:5000/fonts/Roboto-Regular.ttf` 和 `/downloads/<user_id>/...`。

## 日志文件

导出聊天记录的日志会保存在`update_messages.log`文件中，方便排查问题。

## 注意事项

- 确保你有权限访问Telegram聊天记录。
- 导出的JSON文件和生成的HTML文件会保存在当前目录下。