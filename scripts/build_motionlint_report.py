"""Generate matching Markdown/PDF review drafts from measured machine results."""
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'reports/first_prize'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def percent(value):return '-' if value is None else f'{100*value:.2f}%'


def main():
    controlled=read(EVIDENCE/'controlled/summary.json')
    aggregate=read(EVIDENCE/'study/comparisons/development/aggregate.json')
    generation=read(EVIDENCE/'study/generation.json')
    videos=read(EVIDENCE/'study/video_verification.json')
    engineering=read(EVIDENCE/'engineering_verification.json')
    portable=[read(EVIDENCE/f'{folder}/verification.json') for folder in ('portable','portable311')]
    sample_count=sum(s['status']=='succeeded' for s in generation['samples'])
    failures=sum(len(s.get('failed_attempts',[])) for s in generation['samples'])
    full=aggregate['methods']['complete_v4']
    method_names={'unrepaired':'不修复','ordinary_smoothing':'五帧均值平滑','baseline_v3_algorithm':'冻结 v3 算法','complete_v4':'完整 v4 流程','without_contact':'去掉接触约束','without_regression':'去掉回归拒绝'}
    sections=[]
    def section(title, blocks):sections.append((title,blocks))
    section('1. 项目定位与当前范围',[
        ('p','MotionLint：面向 AI 生成动作的自动质检、问题定位、有限修复与回归验证工具。在既有 HumanAction-Platform 上继续开发，InterGen 和 LODGE 作为生成后端；核心工具能够脱离生成环境在 CPU 上使用。'),
        ('p','本稿是待团队审核的工程报告草稿，不是已经完成全部验收的比赛提交。当前包 0.4.0、规则 v4、修复算法 v4；真实准确性、人工语义和外部复现仍待验证。'),
        ('table',(['环节','产物与决策'],[['动作导入 / 生成','统一关节、FPS、坐标轴及单位；记录来源'],['六项检测','问题类型、人物、关节、闭区间、数值与阈值'],['有限修复','接触锚定、IK、局部接缝；所有候选保留'],['全量复测','拒绝超界、骨长退步或新的严重问题'],['阶段复检','对真实导出的 BVH 与角色分别检测'],['复用交付','CLI、规则、报告、示例和自动化质量门']])),
        ('p',f'已保存改动前的 v3 源码、依赖和结果。旧 15 条动作统一作为开发资料，不能称为独立盲测。当前新数据 {sample_count}/30 条成功；开发集完整修复严格门仍为 {full["strict_pass_count"]}/11 PASS。'),
        ('p','设计目的：帮助使用者知道哪里有问题、能否安全修复、最终导出是否仍有问题。总分改善不能代替整体达标，更不能代替动作语义与外观的人工评价。')])
    section('2. 使用场景、已有方案与创新验证',[
        ('p','目标用户：动作生成模型开发者、动画开发者、处理动作数据的学生和研究者。两位同学将分别完成“找到动作问题”和“判断修复是否退步”，记录实际用时、遗漏和错误判断；尚无实测用户成本和反馈。'),
        ('table',(['比较对象','已有能力','本项目的验证方向'],[['InterGen','双人生成与模型评测','多来源输入、逐区间定位、候选审计'],['LODGE','音乐生成、脚滑指标、Foot Refine Block','接触约束下的有界修复与全量回归拒绝'],['PyMotion','BVH / FK / 旋转基础工具','质量门、报告及可自动化工作流'],['Blender','动画编辑、重定向、人工观看','导出后实际骨架复检']])),
        ('p','三个有限主张：① 多来源统一检测并定位区间；② 接触约束的有限修复并拒绝退步；③ 对实际 BVH 与角色再次检查。均需对照实验和人工证据，不能把“调用开源生成模型”或“首次修复脚滑”作为原创结论。'),
        ('p','人工任务采用不同、难度匹配的开发动作组，并交换工具使用顺序，减少记忆影响。原始标注页面不显示工具告警；两位同学独立完成全部新动作后，复核者才裁决分歧。'),
        ('p','比较资料来自项目官方仓库及功能说明，不是完整文献综述。创新表述将随盲测结果收窄，不保证比赛奖项。')])
    section('3. 检测与修复的工程约定',[
        ('table',(['检测','物理含义与边界'],[['连续性','根步长 / 局部旋转步长；FPS 来自明确输入'],['骨架完整性','骨长变化、关节坍缩；需要可靠父子映射'],['脚滑','先估计支撑区间，再检查水平速度；不按低水平速度反推支撑'],['地面接触','显式地面优先；无接触标记时不把腾空自动算悬浮'],['骨架近距风险','头 / 手臂 / 躯干距离，不等于网格穿透'],['jerk','按 FPS 的三次幂计算三阶位置差分，短序列未评估']])),
        ('p','脚滑比较固定原输入的支撑区间：D = Σ ||p(t+1)-p(t)||（只取水平分量与原支撑相邻帧）。修复后不能通过重新判成腾空来隐去原脚滑。'),
        ('p','按脚滑、接缝、局部碰撞的顺序尝试有限候选。接缝仅修改告警边界及告警通道，正常连续动作无需修复。每步关节位移界分别检查，总位移从最初输入计算并限制为 0.20 m。'),
        ('p','骨长指标退步、新严重问题、超界或整体回归的候选拒绝；原输入不覆盖。区分无需修复、当前不支持、接受、拒绝和执行失败。实验消融放松指定机制，仅用于研究比较。'),
        ('p','报告保留格式版本、规则版本 / SHA256、输入文件 SHA256、实际评估数组 SHA256、阶段和覆盖情况。未评估不能成为完整质量门 PASS。不同规则报告拒绝直接比较，必须统一规则重新检测。'),
        ('p','LODGE 在本机使用已获许可的 SMPL-X 几何；无模型时使用固定代理并记录来源。跨机器比较须统一几何条件，模型文件不随核心包分发。')])
    section('4. 可控缺陷验证',[
        ('p','自制 22 关节骨架，六类缺陷 × 三个强度 × 五组种子 = 90 条，另加 30 条无注入对照，共 120 条。保存注入区间、关节、强度及输入哈希；独立计算核只读取数组和注入清单，不导入 MotionLint 检测器。'),
        ('table',(['检测项','TP / FP / FN','Precision','Recall','F1'],[[name,str((v['tp'],v['fp'],v['fn'])),f'{v["precision"]:.2f}',f'{v["recall"]:.2f}',f'{v["f1"]:.2f}'] for name,v in controlled['tests'].items()])),
        ('p',f'宏平均 F1 = {controlled["macro_f1"]:.2f}。同类型、同人物，区间 IoU ≥ 0.5，采用一对一最大匹配，不能用一个预测重复命中多个真值。'),
        ('p','明确限制：集合围绕单一程序姿态构造、缺陷较清楚，变化主要是体型与注入位置。只评估注入的目标检测项，其他附带异常未标注为负例；干净对照分别参加六项检测。'),
        ('p','所有命中时 bootstrap 区间退化为 [1,1]，这反映该可控集合，不能证明对真实动作泛化。可控 F1 不是人工确认的准确率，更不是“真实动作 100% 准确”。'),
        ('p',f'规则哈希：{controlled["config_sha256"]}。对应结果与独立数值核验位于 reports/first_prize/controlled。')])
    section('5. 新生成动作、人工真值与盲测',[
        ('table',(['来源','数量与划分','固定条件'],[['InterGen','8 类 × 3 种子 = 24','握手、击掌、挥手、并行走、舞蹈、鞠躬、指向、侧移；180 帧 / 30 FPS'],['LODGE','6 条真实音乐 = 6','Kevin MacLeod，Incompetech CC BY 4.0；36 秒输入；API 未控制生成随机种子'],['总体','开发 11 / 盲测 19','提示词类别、音乐输入在检测前冻结划分；未查看盲测告警']])),
        ('p',f'全部 30 条成功生成，保留 {failures} 次 LODGE 历史失败尝试。局部补丁解决歌曲编号被字母 g 截断的拼接错误；内存映射后仍出现过一次检查点加载访问异常，不声称崩溃根因完全消除。'),
        ('p',f'全部 {len(videos["rows"])} 个视频完整解码，帧数匹配原数组。InterGen 为 180 帧 / 6 秒；LODGE 为 1024 帧 / 34.133 秒，36 秒音乐最后约 1.867 秒未覆盖，不能声称完整音乐覆盖。'),
        ('p','两位同学独立标注类型、人物、关节、闭区间及不确定/预期接触，再由复核者记录裁决。检测报告不能充当真值。工具已支持恢复自己的标注、生成待裁决表、核验标注输入哈希、FPS 与人物数量。'),
        ('p','真实准确率、一致性、语义保持及按动作样本 bootstrap 范围均待人工完成，当前不填数值。开发集校准结束后冻结代码/规则，再执行盲测。后续若查看盲测后继续调参，需另建测试集。'),
        ('p','固定六条盲测原动作额外导出 BVH 和最终 Kenney 角色，审计四个阶段与视频完整性；这些导出不能重复计为新增样本。目前只有阶段清单与审计工具，尚未完成新盲测阶段实验。')])
    section('6. 开发集对照与消融结果',[
        ('p','固定 11 条开发输入，在同一 v4 规则下比较六种方法，共 66 组。冻结 v3 算法产生的候选重新以 v4 检查，未直接相减不同规则总分。'),
        ('table',(['方法','支撑距离降低中位数','严格 PASS','回归数','最大位移 m'],[[method_names[name],percent(aggregate['methods'][name]['median_original_support_distance_reduction']),f'{aggregate["methods"][name]["strict_pass_count"]}/11',str(aggregate['methods'][name]['regression_count']),f'{aggregate["methods"][name]["max_joint_shift_m"]:.3f}'] for name in method_names])),
        ('p',f'完整流程尝试 {full["candidate_attempt_count"]} 个候选，其中 {full["accepted_candidate_count"]} 个符合接受条件、{full["rejected_candidate_count"]} 个拒绝，执行失败 {full["failed_candidate_count"]} 个。候选数不等于动作数，每步仅选择一个最终候选；原问题与残余问题保留。'),
        ('p','结果表明约束会限制物理改善幅度，同时减少按当前规则识别的回归；尚不能证明视觉自然或语义保持。总体回归不是全部指标绝对不下降的声明，具体拒绝规则和小幅波动均可复查。'),
        ('p','本表的滑动距离统计包含所有原支撑距离非零的开发动作，尚无人工确认的脚滑子集，不能直接宣称已达到真实脚滑修复验收目标。严格门均 0/11，保留全部失败。'),
        ('p',f'完成 {len(aggregate["seed_selection"])} 组开发提示词的三种子质量排序，与固定第一条选择对照；人工提示词语义检查待完成。去掉导出复检的第三项消融须在六条实际导出后计算，当前没有结果。')])
    section('7. 独立安装、自动化与开放边界',[
        ('p',f'完整本机 Python MotionLint 回归：{engineering["python_test_count"]} 项通过；时间轴人物区分与前端生产构建通过。两个仓库外的 Windows 新环境分别安装 wheel，核心 9 项测试通过；生成服务模块不可导入，示例检查/修复/比较正常执行。'),
        ('table',(['验证环境','实际状态'],[[p['python'].split()[0]+' / Windows','安装后 9 项核心测试通过；预期 CLI 退出码 0 / 1 / 1 / 1'] for p in portable]+[['Linux / GitHub Actions','已配置 Linux + Windows、Python 3.10 + 3.11；远程未执行，Linux 未实测'],['外部同学安装','待真实安装与反馈，不用开发者新环境替代']])),
        ('p','核心命令保留 check / repair / compare / batch，统一 --config；BVH 使用显式单位、轴和映射。退出码：0 通过，1 质量失败或回归，2 输入或运行错误。报告可以随 GitHub Actions 保存，正式门不吞掉失败退出码。'),
        ('p','0.4.0 wheel、源码及证据均为本地审阅候选，尚未发布。新增纯自研且权属确认的部分拟采用 MIT；遗留连续性/手臂辅助代码与代理骨架数值需审核，不能把整个上游改为 MIT。'),
        ('p','权重、SMPL-X、FBX、真实数据/音乐不进入核心公开候选。音乐输入另有 CC BY 4.0 署名；默认角色使用 Kenney CC0，奶龙仅为本地扩展。上游补丁保存但未发送，不能称为已获社区采纳。')])
    section('8. 限制、剩余验收与答辩依据',[
        ('p','当前不能回答“真实动作准确率有多高”或“已获得一等奖标准”。缺少独立人工真值、用户任务计时、语义比较、外部安装、新六条最终导出及完整盲测。所有指标均保留其集合、规则与阶段条件。'),
        ('p','剩余顺序：独立标注和用户任务 → 开发集纠错/校准 → 冻结规则 → 19 条盲测及人工一致性 → 六条阶段审计与第三项消融 → 外部安装反馈 → 权利确认及公开 → 正式材料审核、录制与提交。'),
        ('p','答辩准备：为何先用可解释规则？如何获得人工真值与区间匹配？骨架近距和网格穿透有何差异？为何改善候选会被拒绝？核心工具如何脱离模型独立使用？每个回答需引用对应源码、冻结输入和机器记录。'),
        ('p','AI 辅助说明：代码、测试、文档及实验工具使用 AI 辅助开发；已执行自动测试、实际生成和文件验证。团队实际分工、成员审阅及用户反馈尚需团队据实补充，不把未发生的审阅写成完成。生成模型来自开源上游，没有重训声明。'),
        ('p','正式材料需按赛事规范最终人工核验：报告 PDF ≤10 MB，正文建议 ≤15 页；视频 MP4 3-5 分钟、≤300 MB；不得出现学校和指导教师信息。本稿尺寸/页数自动检查，最终视频及提交仍待审核。'),
        ('p','来源：AIC 赛道说明 https://www.aicomp.cn/tracks/tracks-5/4924.html；官方规则附件链接见 Markdown 正文。InterGen: https://github.com/tr3e/InterGen；LODGE: https://github.com/li-ronghui/LODGE；PyMotion: https://github.com/UPC-ViRVIG/pymotion；音乐许可: https://incompetech.com/music/royalty-free/licenses/。')])

    md=['# MotionLint 工程报告草稿 v4','','本地审阅候选，未完成人工盲测验收。','']
    for title,blocks in sections:
        md+=['## '+title,'']
        for kind,content in blocks:
            if kind=='p':md += [content,'']
            else:
                heads,rows=content;md+=['| '+' | '.join(heads)+' |','| '+' | '.join('---' for _ in heads)+' |']
                md += ['| '+' | '.join(map(str,row))+' |' for row in rows];md+=['']
    md += ['## 工作流源图','','```mermaid','flowchart LR','    accTitle: MotionLint 工具工作流','    accDescr: 输入经过六项检测，有限修复并全量复测，最后独立审计实际导出的动画。','    A[导入或生成] --> B[六项检测] --> C[问题定位] --> D[有界候选修复]','    D --> E[全量复测与退步拒绝] --> F[实际导出阶段复检]','```','','[官方规则附件](https://www.aicomp.cn/wp-content/uploads/2026/08/%E9%99%84%E4%BB%B61_AIC%C2%B7AI%E5%BC%80%E6%BA%90%E7%AB%9E%E8%B5%9B%E8%A7%84%E5%88%99%E5%8F%8A%E4%BD%9C%E5%93%81%E6%8F%90%E4%BA%A4%E8%A6%81%E6%B1%820812.pdf)','','结果来源：reports/first_prize；报告生成器只读取实际结果，没有补写人工准确率。']
    (ROOT/'docs/MOTIONLINT_REPORT_V4.md').write_text('\n'.join(md),encoding='utf-8')
    pdfmetrics.registerFont(TTFont('MotionCN','C:/Windows/Fonts/Deng.ttf'))
    pdfmetrics.registerFont(TTFont('MotionCNBold','C:/Windows/Fonts/Dengb.ttf'))
    body=ParagraphStyle('body',fontName='MotionCN',fontSize=10.3,leading=17.2,textColor=colors.HexColor('#25374a'),spaceAfter=11,wordWrap='CJK')
    heading=ParagraphStyle('heading',fontName='MotionCNBold',fontSize=21,leading=29,textColor=colors.HexColor('#173754'),spaceAfter=18,wordWrap='CJK')
    cell=ParagraphStyle('cell',parent=body,fontSize=9,leading=14,spaceAfter=0)
    def para(value,style=body):return Paragraph(escape(str(value)),style)
    output=ROOT/'output/pdf/motionlint_v4_review.pdf';output.parent.mkdir(parents=True,exist_ok=True)
    story=[]
    for page,(title,blocks) in enumerate(sections):
        if page:story.append(PageBreak())
        story.append(para(title,heading))
        if page==0:story.append(para('可独立使用 · 结果可追溯 · 改善与达标分开',body))
        for kind,content in blocks:
            if kind=='p':story.append(para(content))
            else:
                heads,rows=content;n=len(heads)
                table=Table([[para(c,cell) for c in row] for row in [heads]+rows],colWidths=[171*mm/n]*n,hAlign='LEFT',repeatRows=1)
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5edf5')),('BACKGROUND',(0,1),(-1,-1),colors.HexColor('#f7f9fb')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#a8b8c9')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
                story += [table,Spacer(1,14)]
    def decorate(canvas,doc):
        canvas.setTitle('MotionLint 工程报告草稿 v4');canvas.setAuthor('MotionLint')
        canvas.setFont('MotionCN',9);canvas.setFillColor(colors.HexColor('#64788c'))
        canvas.drawString(20*mm,283*mm,'MotionLint 0.4.0 / v4 - 本地审阅草稿')
        canvas.drawRightString(190*mm,12*mm,f'{doc.page}');canvas.drawString(20*mm,12*mm,'未完成独立人工验收，不作最终提交结论')
    doc=SimpleDocTemplate(str(output),pagesize=(210*mm,297*mm),leftMargin=20*mm,rightMargin=19*mm,topMargin=27*mm,bottomMargin=23*mm)
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    pages=len(PdfReader(output).pages)
    validation={'status':'draft_generated_visual_review_pending','pages':pages,'bytes':output.stat().st_size,'page_limit_ok':pages<=15,'size_limit_ok':output.stat().st_size<=10_000_000,'generated_utc':datetime.now(timezone.utc).isoformat(),'human_validation':'pending','data_sources':['controlled/summary.json','study/comparisons/development/aggregate.json','study/generation.json','study/video_verification.json','engineering_verification.json','portable/verification.json','portable311/verification.json']}
    (EVIDENCE/'report_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(validation,ensure_ascii=False,indent=2))
    if not validation['page_limit_ok'] or not validation['size_limit_ok']:raise ValueError('Draft exceeds submission size/page limit')


if __name__=='__main__':main()
