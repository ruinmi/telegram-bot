# Telegram Bot 聊天记录导出与HTML生成工具

## 项目简介

该项目包含两个主要功能：
1. 导出Telegram聊天记录并保存为JSON文件。
2. 将导出的聊天记录生成HTML文件，方便浏览和搜索。

## 文件说明

- `update_messages.py`：负责导出Telegram聊天记录并保存为JSON文件。
- `generate_html.py`：负责将JSON格式的聊天记录转换为HTML文件。

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
python generate_html.py <user_id>
```
其中，`<user_id>`是你要生成HTML文件的用户ID。

如果你已经导出过聊天记录，可以使用`--ne`选项跳过导出步骤：
```bash
python generate_html.py <user_id> --ne
```

## 日志文件

导出聊天记录的日志会保存在`update_messages.log`文件中，方便排查问题。

## 注意事项

- 确保你有权限访问Telegram聊天记录。
- 导出的JSON文件和生成的HTML文件会保存在当前目录下。