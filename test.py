import re
msg_text = '【这是贵州脆哨～不是油滋啦！好吃到停不下来啊！】 https://www.bilibili.com/video/BV1YYykY4Eb3/?share_source=copy_web&vd_source=0e9fbdc10133ffe6c55b8901d19fc9ed 准备做这个😋'
links = re.findall(r'(https?://\S+)', msg_text)
print(links)