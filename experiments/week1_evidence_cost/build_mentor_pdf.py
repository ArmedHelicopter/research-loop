
from pathlib import Path
import re,json
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
from pypdf import PdfReader
P=Path(__file__).resolve().parent
out=P/'output/pdf';out.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('Song','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
bold='C:/Windows/Fonts/simhei.ttf'
pdfmetrics.registerFont(TTFont('Hei',bold if Path(bold).exists() else 'C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
pdfmetrics.registerFontFamily('Song',normal='Song',bold='Hei',italic='Song',boldItalic='Hei')
body=ParagraphStyle('body',fontName='Song',fontSize=9.5,leading=14.4,wordWrap='CJK',spaceAfter=7,textColor=colors.HexColor('#253249'))
title=ParagraphStyle('title',parent=body,fontName='Hei',fontSize=20,leading=26,spaceAfter=9,textColor=colors.HexColor('#152942'))
sub=ParagraphStyle('sub',parent=body,fontSize=8.8,leading=12.5,textColor=colors.HexColor('#66738a'),spaceAfter=13)
cell=ParagraphStyle('cell',parent=body,fontSize=8.7,leading=12,spaceAfter=0)
def inline(s):return re.sub(r'\*\*(.*?)\*\*',r'<b>\1</b>',s).replace('&','&amp;')
lines=(P/'MENTOR-DECISION.md').read_text(encoding='utf-8').splitlines()
story=[];table=[]
def flush():
 if not table:return
 t=Table([[Paragraph(inline(v),cell) for v in row] for row in table],colWidths=[171,92,117,131],repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8eff6')),('LINEBELOW',(0,0),(-1,0),.65,colors.HexColor('#9bacbf')),('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#dce2eb')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
 story.extend([t,Spacer(1,10)]);table.clear()
for i,line in enumerate(lines):
 if line.startswith('|'):
  if not re.fullmatch(r'[\s|:-]+',line):table.append([x.strip() for x in line.strip('|').split('|')])
  continue
 flush()
 if not line:continue
 style=title if line.startswith('# ') else sub if line.startswith('2026-') else body
 if line.startswith('# '):line=line[2:]
 story.append(Paragraph(inline(line),style))
flush()
target=out/'mentor-decision.pdf'
def page(canvas,doc):
 canvas.saveState();canvas.setStrokeColor(colors.HexColor('#d9e1eb'));canvas.line(42,34,553,34)
 canvas.setFont('Song',8);canvas.setFillColor(colors.HexColor('#64748b'));canvas.drawString(42,22,'research-loop · 有界成本研究 · 原始证据与失败均保留');canvas.drawRightString(553,22,str(doc.page));canvas.restoreState()
SimpleDocTemplate(str(target),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=36,bottomMargin=44,title='证据查询与缓存：本轮研究决定',author='research-loop').build(story,onFirstPage=page,onLaterPages=page)
r=PdfReader(str(target));text='\n'.join(p.extract_text() for p in r.pages)
assert len(r.pages)==1,('expected one page',len(r.pages))
for item in ('720','17.22','AND','needs_review','46/60'):assert item in text,item
print(json.dumps({'pdf':str(target),'pages':len(r.pages),'required_text_checks':5,'bytes':target.stat().st_size},ensure_ascii=False))

