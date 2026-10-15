# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy", "reportlab", "pypdf", "pillow"]
# ///
"""Render the machine-generated Markdown, verify figures and report constraints."""
import json
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape


def render_charts(root,data,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    # --- Style Setup ---
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.labelcolor':'dimgrey',
        'text.color':'dimgrey','xtick.color':'dimgrey','ytick.color':'dimgrey'})
    # --- Data ---
    methods=['none','time_smooth','historical_v5','repair_v6','no_contact','no_regression']
    names=['No repair','Time smoothing','Historical v5','Full v6','Without contact','Without rejection']
    values=[data['methods']['v5']['holdout_real'][name]['strict_pass_count'] for name in methods]
    # --- Plot ---
    fig,ax=plt.subplots(figsize=(7.5,4.1),dpi=150)
    bars=ax.barh(names[::-1],values[::-1],color=['#58849f']*6,height=.62)
    for bar in bars:
        ax.text(bar.get_width()+.4,bar.get_y()+bar.get_height()/2,f'{int(bar.get_width())}/36',va='center',color='dimgrey')
    ax.set_xlim(0,38);ax.set_xticks([]);ax.tick_params(length=0)
    ax.set_title('Strict quality passes on retained real inputs',loc='left',pad=14)
    for spine in ax.spines.values():spine.set_visible(False)
    regressions=data['methods']['v5']['holdout_real']['no_regression']['regression_count']
    fig.text(.98,.012,f'Removing rejection admits {regressions} regressions; no human semantic truth',ha='right',fontsize=9,color='dimgrey')
    fig.tight_layout(rect=(0,.045,1,1))
    # --- Save ---
    fig.savefig(out/'real-methods.png',dpi=150,bbox_inches='tight');fig.savefig(out/'real-methods.pdf',bbox_inches='tight');plt.close(fig)
    fig,ax=plt.subplots(figsize=(7.5,4.1),dpi=150)
    categories=list(data['controlled']['per_class'])
    short=['Continuity','Skeleton','Foot sliding','Ground','Skeleton distance','Jerk']
    bars=ax.barh(short[::-1],[data['controlled']['per_class'][key]['f1'] for key in categories][::-1],color='#58849f',height=.62)
    for bar in bars:ax.text(bar.get_width()+.025,bar.get_y()+bar.get_height()/2,f'{bar.get_width():.2f}',va='center',color='dimgrey')
    ax.set_xlim(0,1.18);ax.set_xticks([]);ax.tick_params(length=0)
    ax.set_title('Controlled retained injections: per-class F1',loc='left',pad=14)
    for spine in ax.spines.values():spine.set_visible(False)
    fig.text(.98,.012,'54 injections per class; analytic trajectories, not real-motion accuracy',ha='right',fontsize=9,color='dimgrey')
    fig.tight_layout(rect=(0,.045,1,1));fig.savefig(out/'controlled-f1.png',dpi=150,bbox_inches='tight');fig.savefig(out/'controlled-f1.pdf',bbox_inches='tight');plt.close(fig)
def main():
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'evidence/iteration-050-results.json').read_text(encoding='utf-8'))
    out=root/'output/pdf';out.mkdir(parents=True,exist_ok=True)
    if '--reuse-charts' in sys.argv:
        for name in ('real-methods.png','controlled-f1.png'):
            if not (out/name).is_file():raise FileNotFoundError(name)
    else:
        render_charts(root,data,out)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,KeepTogether,PageBreak
    font=Path('C:/Windows/Fonts/simhei.ttf')
    if not font.exists():raise ValueError('Set a CJK TTF before rendering the Chinese report')
    pdfmetrics.registerFont(TTFont('MotionCN',str(font)))
    pdfmetrics.registerFontFamily('MotionCN',normal='MotionCN',bold='MotionCN',italic='MotionCN',boldItalic='MotionCN')
    styles=getSampleStyleSheet()
    for name in ('Normal','BodyText','Heading1','Heading2','Heading3','Title'):
        styles[name].fontName='MotionCN';styles[name].wordWrap='CJK';styles[name].textColor=colors.HexColor('#213c50')
    styles['BodyText'].fontSize=10;styles['BodyText'].leading=16;styles['BodyText'].spaceAfter=8
    styles['Title'].fontSize=22;styles['Title'].leading=30;styles['Title'].spaceAfter=20
    styles['Heading2'].fontSize=13;styles['Heading2'].leading=20;styles['Heading2'].spaceBefore=14;styles['Heading2'].spaceAfter=8;styles['Heading2'].keepWithNext=True
    styles.add(ParagraphStyle('Cell',fontName='MotionCN',fontSize=8.5,leading=13,wordWrap='CJK',textColor=colors.HexColor('#213c50')))
    styles.add(ParagraphStyle('Notice',parent=styles['BodyText'],fontSize=9,leading=14,spaceAfter=5))
    def inline(text):
        escaped=escape(text.replace('`',''))
        def link(match):
            target=match[2]
            if target.startswith('../'):
                target='https://github.com/TiAmo0323/AIC/blob/v0.5.0/'+target[3:]
            return f'<link href="{target}" color="#226286">{match[1]}</link>'
        return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,escaped)
    text=(out/'MotionLint-050-report.md').read_text(encoding='utf-8')
    lines=text.splitlines();story=[];paragraph=[];table=[]
    def flush():
        if paragraph:story.append(Paragraph(inline(' '.join(paragraph)),styles['BodyText']));paragraph.clear()
    def flush_table():
        if not table:return
        rows=[[Paragraph(inline(c.strip()),styles['Cell']) for c in line.strip('|').split('|')] for line in table]
        widths=[495/len(rows[0])]*len(rows[0])
        if len(rows[0])==5:widths=[155,85,85,85,85]
        if len(rows[0])==3:widths=[125,185,185]
        t=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f4')),
            ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#8ca5b8')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#dce5ec'))]))
        group=[t,Spacer(1,12)]
        if story and isinstance(story[-1],Paragraph) and story[-1].style.name=='Heading2':group.insert(0,story.pop())
        story.append(KeepTogether(group));table.clear()
    for line in lines:
        if line.startswith('|'):
            flush()
            if not re.match(r'^\|[ :|\-]+\|$',line):table.append(line)
            continue
        flush_table()
        if line.startswith('#'):
            flush();level=len(line)-len(line.lstrip('#'));title=line.lstrip('#').strip()
            heading=Paragraph(inline(title),styles['Title'] if level==1 else styles['Heading2'])
            chart='real-methods.png' if '真实保留输入' in title else 'controlled-f1.png' if '数据与独立证据' in title else None
            if chart:story.append(KeepTogether([heading,Image(str(out/chart),width=480,height=262),Spacer(1,12)]))
            else:story.append(heading)
        elif not line.strip():flush()
        else:paragraph.append(line)
    flush();flush_table()
    story.append(PageBreak())
    story.append(Paragraph('附录：第三方资源与自主开发边界',styles['Heading2']))
    notices=(root/'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    for line in notices.splitlines():
        if line.startswith('|') and not re.match(r'^\|[ :|\-]+\|$',line):
            story.append(Paragraph(inline(' · '.join(c.strip() for c in line.strip('|').split('|'))),styles['Notice']))
    story.append(Paragraph('AI 辅助说明：本轮使用 AI 编码助手实施代码、实验运行、浏览器操作及材料自动生成；生成模型为官方 InterGen。维护者已确认独立组件及三个遗留辅助文件的 MIT 开放授权，第三方权利保持独立。本轮没有人工标注、访谈或外部用户安装；本文不作为其他作者已签署的声明。',styles['BodyText']))
    def footer(canvas,doc):
        canvas.setFont('MotionCN',8);canvas.setFillColor(colors.HexColor('#607487'))
        canvas.drawString(48,28,'MotionLint 0.5.0 · 自动工程证据 / 参赛技术报告')
        canvas.drawRightString(A4[0]-48,28,str(doc.page))
    report=out/'MotionLint-050-report.pdf'
    SimpleDocTemplate(str(report),pagesize=A4,leftMargin=50,rightMargin=50,topMargin=48,bottomMargin=46,
        title='MotionLint 动作质量工具',author='MotionLint',allowSplitting=1).build(story,onFirstPage=footer,onLaterPages=footer)
    from pypdf import PdfReader
    reader=PdfReader(report);extracted='\n'.join(p.extract_text() for p in reader.pages)
    forbidden=[r'[A-Za-z]:[\\/]Users[\\/]',r'HumanAction-runtime',r'竞赛记录',r'zzz',r'指导教师\s*[:：]']
    hits=[pattern for pattern in forbidden if re.search(pattern,extracted)]
    check={'schema_version':3,'report_bytes':report.stat().st_size,'pages':len(reader.pages),
        'size_limit_met':report.stat().st_size<=10*1024**2,'page_target_met':len(reader.pages)<=15,
        'private_path_or_identity_hits':hits,'source_results':'evidence/iteration-050-results.json',
        'identity_scan_limit':'Pattern scan plus visual review; no school or teacher identity was supplied or inserted'}
    (out/'report-validation.json').write_text(json.dumps(check,indent=2),encoding='utf-8')
    assert check['size_limit_met'] and check['page_target_met'] and not hits,check
    print('PDF verified',len(reader.pages),'pages',report.stat().st_size,'bytes')


if __name__=='__main__':main()
