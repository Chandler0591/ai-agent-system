from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# 注册中文字体（解决中文方块乱码）
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
FONT_CN = 'STSong-Light'

# 读取文本
with open("test.txt", "r", encoding="utf-8") as f:
    content = f.read()

# 生成PDF
c = canvas.Canvas("test.pdf", pagesize=A4)
c.setFont(FONT_CN, 12)
x, y = 40, 820
line_height = 22

for line in content.splitlines():
    c.drawString(x, y, line)
    y -= line_height
    # 分页简易处理
    if y < 50:
        c.showPage()
        c.setFont(FONT_CN, 12)
        y = 820

c.save()
print("生成成功: test.pdf")
