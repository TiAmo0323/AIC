"""Build the review draft for the AIC MotionLint technical report.

Run with the motionlint environment after installing reportlab. The PDF is a
draft: team ownership, music rights, and the final open-source choice require
human review before submission.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "motionlint_aic_draft.pdf"
FONT_DIR = Path("C:/Windows/Fonts")
pdfmetrics.registerFont(TTFont("Deng", str(FONT_DIR / "Deng.ttf")))
pdfmetrics.registerFont(TTFont("DengBold", str(FONT_DIR / "Dengb.ttf")))

INK = colors.HexColor("#142B41")
MUTED = colors.HexColor("#52687B")
BLUE = colors.HexColor("#2366A4")
PALE = colors.HexColor("#EAF2F9")
GREEN = colors.HexColor("#247760")
RED = colors.HexColor("#A94448")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="CoverTitleCN", fontName="DengBold", fontSize=25, leading=34, textColor=INK, spaceAfter=18))
styles.add(ParagraphStyle(name="CoverSubCN", fontName="Deng", fontSize=13, leading=21, textColor=MUTED, spaceAfter=10))
styles.add(ParagraphStyle(name="HeadCN", fontName="DengBold", fontSize=14, leading=22, textColor=INK, spaceBefore=17, spaceAfter=8))
styles.add(ParagraphStyle(name="SubCN", fontName="DengBold", fontSize=10.5, leading=17, textColor=BLUE, spaceBefore=10, spaceAfter=4))
styles.add(ParagraphStyle(name="BodyCN", fontName="Deng", fontSize=9.5, leading=16, textColor=INK, spaceAfter=7))
styles.add(ParagraphStyle(name="SmallCN", fontName="Deng", fontSize=8, leading=13, textColor=MUTED, spaceAfter=5))
styles.add(ParagraphStyle(name="TableCN", fontName="Deng", fontSize=8, leading=12, textColor=INK))
styles.add(ParagraphStyle(name="TableHeadCN", fontName="DengBold", fontSize=8, leading=12, textColor=colors.white))
styles.add(ParagraphStyle(name="CenterCN", fontName="Deng", fontSize=9.5, leading=16, alignment=TA_CENTER, textColor=MUTED))


def p(text: str, style: str = "BodyCN") -> Paragraph:
    return Paragraph(escape(text), styles[style])


def section(title: str, *paragraphs: str):
    block = [p(title, "HeadCN")]
    block.extend(p(item) for item in paragraphs)
    return block


def table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[p(cell, "TableHeadCN") for cell in headers]]
    data.extend([[p(str(cell), "TableCN") for cell in row] for row in rows])
    result = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, -1), (-1, -1), 0.35, colors.HexColor("#C8D8E5")),
    ]))
    return result


def footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(colors.HexColor("#D5E1E9"))
    canvas.line(22 * mm, 19 * mm, width - 22 * mm, 19 * mm)
    canvas.setFont("Deng", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(22 * mm, 13 * mm, "MotionLint · AIC 技术报告草稿 · 待团队审核")
    canvas.drawRightString(width - 22 * mm, 13 * mm, str(doc.page))
    canvas.restoreState()


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    width, _ = A4
    usable = width - 44 * mm
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=22 * mm,
                            rightMargin=22 * mm, topMargin=24 * mm, bottomMargin=26 * mm,
                            title="MotionLint 人体动作质检平台 - 技术报告草稿", author="MotionLint 项目团队")
    story = []

    story += [Spacer(1, 28 * mm), p("MotionLint 人体动作质检平台", "CoverTitleCN"),
              p("生成式人体动作的自动检测、定位、有限修复与回归验证", "CoverSubCN"),
              HRFlowable(width="100%", thickness=2, color=BLUE), Spacer(1, 13 * mm),
              p("参赛方向：AI 开发工具与开源协作", "CoverSubCN"),
              p("作品形态：Windows 本地 Web 工具、命令行工具、测试与开放文档", "CoverSubCN"),
              Spacer(1, 14 * mm),
              p("本报告是供团队审阅的草稿。团队权属、音乐素材授权、最终许可证与公开范围尚待确认。", "BodyCN"),
              p("实验数据来源：本机既有 InterGen/LODGE 任务及合成异常测试；没有把重复任务当作独立样本。", "SmallCN"),
              PageBreak()]

    story += section("1. 问题与目标",
        "人体动作生成结果可能出现脚底滑动、拼接接缝、骨架异常、地面穿透、人体碰撞与高频抖动。只看最终视频难以稳定定位错误，也难以比较新旧版本的退化程度。",
        "MotionLint 的目标是让已有生成后端输出统一接受质量检查，给出时间点、关节、指标与质量门结果；对少数有明确几何约束的问题尝试修复，并在修复后运行全部测试。")
    story += [p("核心工作流", "SubCN"),
              table(["输入", "自主处理流程", "输出"], [["InterGen 双人 joints22 / LODGE 舞蹈 NPY / BVH", "统一 MotionSequence → 六项检查 → 质量门 → 有限修复 → 全量复测 → 回归比较", "JSON/CSV 报告、问题帧、原始/修复视频"]], [37 * mm, 85 * mm, usable - 122 * mm]),
              Spacer(1, 6 * mm)]
    story += section("2. 系统架构与自主实现",
        "InterGen 提供文本生成双人动作，LODGE 提供音乐生成舞蹈；二者作为本机外部生成运行时。适配器统一帧率、关节顺序、根位移和接触信息；LODGE 检测优先使用本机 SMPL-X 渲染模型的静态骨架。Web、CLI 与批量实验调用同一检测逻辑。",
        "团队代码实现六项几何和时间序列测试、可配置阈值、质量门、问题定位、修复候选的再检测及拒绝条件。InterGen 多候选排序在原有硬碰撞规则之后参考 MotionLint 分数，不声称能够判断文本语义是否正确。")
    story += [PageBreak()]

    story += section("3. 检测与修复方法",
        "脚滑检测计算支撑期间脚关节的水平速度。LODGE 的接触通道多数帧同时为真，因此再结合每个脚关节自身的低位高度估计支撑，避免脚尖与踝关节共用一个高度基准。",
        "LODGE 修复通过所有支撑脚的平均帧间位移估计一个受限的水平根节点修正；原旋转与接触通道保持不变。InterGen 修复针对可定位的关节轨迹进行有限平移。若目标分数或总体分数未提高、严重问题增加，或其他测试下降超过容差，候选修复会被拒绝。",
        "一个根节点不能同时消除两只脚方向相反的滑动；因此修复采用有限目标，剩余问题继续显示在报告中。")
    story += [p("六项测试", "SubCN"), table(["测试", "主要检查对象"], [
        ["Temporal Continuity", "根节点与关节运动的突变和分块接缝"],
        ["Skeleton Integrity", "骨长波动与关节塌缩"],
        ["Foot Sliding", "支撑期间的脚部水平速度"],
        ["Ground Contact", "地面穿透与接触悬空"],
        ["Collision", "头、躯干、手臂等部位间距"],
        ["Motion Jerk", "位置和旋转高频变化"],
    ], [57 * mm, usable - 57 * mm]), PageBreak()]

    story += section("4. 验证设计与结果",
        "验证分两层：先以合成静止动作和注入的水平滑动、接缝跳变验证检测方向与修复基本行为；再对已有生成任务运行批量质检和修复。八个文件批量读取全部成功，但其中包含同一任务的原始/连续化版本与重复握手文件，不作为八个独立生成样本。",
        "在当前严格质量门下，八个文件全部为 FAIL，没有 critical 问题。门限对任一 high 问题零容忍，脚滑、骨长波动与关节距离风险仍存在。静止正常合成动作 PASS；注入每帧 0.008 米水平位移后 FAIL，回归比较识别脚滑退化。",
        "此表为修正 LODGE 骨架后重新复测的结果。旧视频和历史记录使用固定 BVH 骨架，分数不能混用。新骨架与实际 SMPL-X 渲染关节在六帧抽查中的最大坐标误差约 0.00000021 米。")
    story += [p("非重复任务的修复前后结果", "SubCN"), table(
        ["样例", "总分 前→后", "脚滑 前→后", "抖动 前→后", "结果"], [
            ["LODGE aic260929", "89.48→89.96", "68.70→71.86", "84.31→82.72", "接受"],
            ["LODGE 063", "87.19→88.57", "57.29→64.50", "80.40→79.83", "接受"],
            ["InterGen 双人舞蹈", "82.03→84.17", "50.97→63.62", "78.47→75.78", "接受"],
            ["InterGen 握手", "89.36→89.36", "64.49→64.49", "87.98→87.98", "拒绝"],
            ["InterGen 挥手", "87.03→87.03", "52.28→52.28", "88.95→88.95", "拒绝"],
        ], [37 * mm, 32 * mm, 32 * mm, 32 * mm, usable - 133 * mm]),
        Spacer(1, 5 * mm),
        p("接受修复的三条样例仍未通过质量门；抖动分数略降。脚滑分数变化只表示当前判据下的改善，不能代替主观动作质量评价。", "SmallCN"),
        PageBreak()]

    story += section("5. 可运行成果与复现",
        "本机服务包含 InterGen API、LODGE API、MotionLint API 与 Vue 前端。任务结果写入各自 task_runs 目录，重启后仍可从历史任务加载。Web 页面显示六项分数、Quality Gate、问题帧、修复前后分数以及可播放的视频。LODGE 使用本机 SMPL-X 渲染，InterGen 对比使用双人骨架视角。",
        "命令行支持 check、repair、compare 和 batch；默认阈值位于 motionlint/configs/default_quality.yaml。测试不需加载两个生成模型。现有本机环境中，MotionLint 相关 30 项 Python 测试通过，前端生产构建与 InterGen 契约脚本此前已通过。",
        "他人复现需要自行下载允许使用的生成模型和人体模型，并在同级 HumanAction-runtime 中安装。代码仓库不包含权重、SMPL-X NPZ、FBX、音频或生成视频。")
    story += section("6. 开源与第三方资源边界",
        "InterGen 上游声明 CC BY-NC-SA 4.0 与非商业使用要求，InterHuman 数据禁止再分发。SMPL-X 模型许可限定非商业研究、教育或艺术用途，禁止再分发模型。Kenney 角色为 CC0。LODGE 公开仓库截至本次核查未见明确 LICENSE，因此只作为本机外部运行时，不能把其代码和权重当作可任意再分发的开源成果。",
        "开放成果拟包括 MotionLint 的源代码、合成测试、接口与操作文档；正式开放许可、团队成员权属及实际公开范围待团队确认。")
    story += [PageBreak()]

    story += section("7. 限制、AI 工具使用与后续工作",
        "现有实验仅覆盖少量生成任务，LODGE 音乐输入是自制合成节拍，尚无人工标注的真实舞蹈基准。质量门偏严格，所有真实样例仍为 FAIL。InterGen 关节修复尚需更强的骨长与主观画面约束；LODGE 需进一步研究双脚约束和逆运动学。",
        "开发过程使用 Codex 辅助代码阅读、实现、测试运行和文档初稿。团队仍需人工审核代码、结果、来源、授权和最终材料；不能把 AI 生成内容直接认定为团队独立知识产权。",
        "后续计划包括扩展独立音乐与文本样本、人工标注对照、接触时序校准、更稳健的 IK 修复，以及在最终报告中补充团队分工和实际开放链接。")
    story += [p("参考与核验入口", "HeadCN"),
              p("AIC 官方赛题及规则：https://www.aicomp.cn/tracks/tracks-5/4924.html", "SmallCN"),
              p("InterGen：https://github.com/tr3e/InterGen", "SmallCN"),
              p("LODGE：https://github.com/li-ronghui/LODGE", "SmallCN"),
              p("SMPL-X 模型许可：https://smpl-x.is.tue.mpg.de/modellicense.html", "SmallCN"),
              p("Kenney 角色：https://kenney.nl/assets/animated-characters-protagonists", "SmallCN"),
              p("代码与实验细节：README.md、LOCAL_SETUP.md、docs/MOTIONLINT_GATE_DIAGNOSIS_20260930.md、docs/AIC_RESOURCE_LIST.md。", "SmallCN"),
              PageBreak()]

    story += section("附录：开源及第三方资源使用清单",
        "本表是提交附件草稿的摘要。详细版本、下载来源、许可和使用边界记录在 docs/AIC_RESOURCE_LIST.md；提交前需核对到实际使用的文件与公开范围。")
    story += [table(["资源", "来源与用途", "许可状态及公开边界"], [
        ["InterGen", "tr3e/InterGen；文本生成双人动作", "上游 README 声明 CC BY-NC-SA 4.0；检查点授权待核，InterHuman 数据不再分发"],
        ["LODGE", "li-ronghui/LODGE；音乐生成舞蹈", "未见明确 LICENSE；仅本机外部运行，代码和权重不随成果发布"],
        ["SMPL-X", "官方模型；人体网格渲染", "非商业研究、教育或艺术用途；模型文件不再分发"],
        ["Kenney 角色", "Animated Characters Protagonists；角色重定向", "CC0；保留来源记录"],
        ["PyMotion / Blender / FFmpeg", "FK、BVH 和视频处理", "作为单独安装的运行依赖；具体构建和插件许可待核"],
        ["Vue / Vite / FastAPI 等", "Web 与 API 运行依赖", "按依赖清单核对版本与许可证"],
        ["合成节拍音频", "本机技术验证输入", "团队自制，生成过程与参与者待核；不宣称真实音乐数据集验证"],
    ], [37 * mm, 52 * mm, usable - 89 * mm]),
        Spacer(1, 7 * mm),
        p("待团队确认：作品权属、正式开源许可、所用检查点与音频的展示授权、AI 辅助环节及最终发布链接。", "SmallCN")]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return OUTPUT


if __name__ == "__main__":
    print(build())
