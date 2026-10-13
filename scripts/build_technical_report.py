#!/usr/bin/env python3
"""Build the submission PDF from verified evidence; reportlab is authoring-only."""
import argparse
import collections
import datetime
import html
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kylin_memory_bench import __version__
from kylin_memory_bench.common import DIMENSIONS, read_json, digest
from kylin_memory_bench.runner import read_run,verify_run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core',default=str(ROOT/'examples/openkylin-core'))
    p.add_argument('--challenge',default=str(ROOT/'examples/openkylin-challenge'))
    p.add_argument('--environment',default=str(ROOT/'docs/evidence/openkylin-environment.json'))
    p.add_argument('--output',default=str(ROOT/'output/pdf/KylinMemoryBench-technical-report.pdf'))
    p.add_argument('--font',default='C:/Windows/Fonts/simsun.ttc')
    args=p.parse_args()
    runs=[]
    for directory in (args.core,args.challenge):
        verify_run(directory)
        run=read_run(directory)
        if run[0]['status'] not in ('completed','completed_with_errors') or run[0]['repeats']!=3 or not run[0]['environment']['is_openkylin']:
            raise SystemExit('Final PDF requires finished, three-trial openKylin runs; execution errors remain in the report.')
        if len(run[3]['agents'])!=2 or {a['kind'] for a in run[3]['agents']}!={'openclaw','hermes'} or any(a['is_baseline'] for a in run[3]['agents']):
            raise SystemExit('Final report requires both native agents, never rule baselines.')
        runs.append(run)
    if len(runs[0][1])!=36 or len(runs[1][1])!=12:
        raise SystemExit('Expected 36 core and 12 challenge cases.')
    env=read_json(args.environment)
    from reportlab.pdfgen import canvas
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,KeepTogether
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.enums import TA_LEFT
    if Path(args.font).is_file(): pdfmetrics.registerFont(TTFont('CJK',args.font,subfontIndex=0))
    else: pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    font='CJK' if Path(args.font).is_file() else 'STSong-Light'
    ink=colors.HexColor('#173c32'); green=colors.HexColor('#0f8b73'); muted=colors.HexColor('#65786f'); pale=colors.HexColor('#edf3ed')
    styles={
        'body':ParagraphStyle('body',fontName=font,fontSize=10.3,leading=18,textColor=ink,spaceAfter=10,wordWrap='CJK'),
        'small':ParagraphStyle('small',fontName=font,fontSize=8.6,leading=14,textColor=muted,spaceAfter=7,wordWrap='CJK'),
        'title':ParagraphStyle('title',fontName=font,fontSize=26,leading=35,textColor=ink,spaceAfter=16,wordWrap='CJK'),
        'h2':ParagraphStyle('h2',fontName=font,fontSize=14.5,leading=22,textColor=green,spaceBefore=15,spaceAfter=9,wordWrap='CJK'),
        'cell':ParagraphStyle('cell',fontName=font,fontSize=9,leading=14,textColor=ink,wordWrap='CJK'),
        'white':ParagraphStyle('white',fontName=font,fontSize=9,leading=14,textColor=colors.white,wordWrap='CJK'),
    }
    story=[]
    def para(text,style='body'):
        story.append(Paragraph(text,styles[style]))
    def esc(value): return html.escape(str(value))
    def table(headers,rows,widths=None):
        data=[[Paragraph(esc(x),styles['white']) for x in headers]]+[[Paragraph(esc(x),styles['cell']) for x in row] for row in rows]
        t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),ink),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,pale]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,0),.5,ink)]))
        story.append(t);story.append(Spacer(1,10))
    def page(kicker,title,subtitle=None):
        if story: story.append(PageBreak())
        para('KYLIN MEMORY BENCH / '+kicker,'small');para(title,'title')
        if subtitle: para(subtitle,'small')
    def pct(v): return '未观测' if v is None else f'{100*v:.2f}%'
    core,challenge=runs
    challenge_raw=challenge
    from review_challenge import calculate
    _,reviewed_cases,reviewed_scores,annotation_review=calculate(Path(args.challenge))
    challenge=(challenge[0],reviewed_cases,challenge[2],reviewed_scores)
    events_total=sum(len(r[2]) for r in runs)
    check_total=sum(sum(len(c['checks']) for c in a['cases']) for r in runs for a in r[3]['agents'])
    page('TECHNICAL REPORT','让长期记忆的能力，<br/>有证据可查。','openKylin 智能体长期记忆自动化评测工具 / 技术方案与实测报告')
    story.append(Spacer(1,28))
    para('Kylin Memory Bench','title')
    para('版本 '+__version__+' · 提交材料版 · '+datetime.date.today().isoformat())
    table(['评测维度','数据规模','真实被测系统'],[['六个维度','36 标准案例 + 12 挑战案例','OpenClaw + Hermes'],['三轮独立重复',f'{events_total:,} 交互事件 / {check_total:,} 判分项','同一 DeepSeek Flash 模型']],[120,220,145])
    para('从用户对话到持久记忆，从原生工具轨迹到真实文件：统一采集四类证据，保留失败与未知项，以可独立重放的确定性规则评分。')
    para('实测环境：openKylin 2.0 SP1 用户空间，运行于本机已有 WSL 2；UKUI 桌面通过本地显示会话呈现。此环境不代表裸机、专用 openKylin 内核或所有硬件适配认证。','small')
    para('交付入口：START_HERE.md。先查看报告，再运行 verify-delivery.py 校验文件与评分；无需重新调用模型即可复核实测结果。','small')

    page('01 / OVERVIEW','项目解决的问题')
    para('长期记忆评测容易把“回答像是记住了”当作“确实保存并正确复用了”。只看最终回答，无法区分未持久化、检索遗漏、旧值覆盖、项目串扰和工具执行失败；只看总分，又会掩盖不可观测的存储。')
    para('本项目将一次独立案例定义为多个会话及明确的状态变化。在同一案例中保留记忆目录、更换会话标识；在不同系统、案例和重复轮次间创建新目录。标准答案留在评测器中，原生智能体只接收当前提示和模拟时间。')
    table(['核心能力','可核验的交付'],[
        ['统一证据','回答、记忆文件、工具记录、实际产物都进入同一事件结构。'],
        ['明确未知','完整快照与部分快照分开；缺证据不直接算成功或能力失败。'],
        ['可复现结果','种子、数据和配置指纹、源码指纹、隔离目录、逐事件散列链、独立重评分。'],
        ['原生系统验证','在 openKylin 原生 Python 上执行框架，调用真实 OpenClaw/Hermes CLI 和同一模型服务。'],
        ['可解释结果','HTML 雷达图、逐项评分、离线证据检查器、CSV/JSON/SVG 和安装包。']],[105,380])
    para('工程价值在于证据与复核流程的闭环。本项目不把小规模合成集宣称为自然用户分布的代表，也不将两个系统在此配置下的成绩外推为通用排名。')

    page('02 / REQUIREMENTS','赛题要求与实现对应')
    table(['赛题评价项','权重','实现与证据'],[
        ['任务设计与通用性','15%','六维标准集和独立挑战集；版本化 JSONL；通用命令适配器及两个原生适配器。'],
        ['数据构建','25%','标准集 36 例、挑战集 12 例；正负对照、随机事实、会话干扰、动态更正与授权撤销。'],
        ['自动评分','25%','四种状态、严格类型与 JSON Pointer、文件验证、部分存储约束、原生工具结果。'],
        ['稳定与复现','15%','三轮重复、事件落盘、失败留痕、并发隔离、固定依赖、源码冻结、离线 verify。'],
        ['指标完整性','10%','六维宏平均、覆盖率、上下界、重复标准差、错误类别和 P50/P95 延迟。'],
        ['创新与工程','10%','跨系统原生证据规范化、可离线逐事件检查、低依赖 CLI、.deb 和费用受控实验。']],[130,45,310])
    para('交付 a-d：方案、数据与样例、源代码与复现脚本、一键 CLI/批量比较与安装包均包含在交付目录。交付 e：真实桌面和双系统结果已准备，3-5 分钟最终演示视频由提交者录制；详见 docs/demo-video.md。')
    para('原始依据：项目根目录赛题计划书 PDF，第 1-3 页。此处只给出本项目落实方式，不构成主办方验收结论。','small')

    page('03 / PROTOCOL','一次可重放的实验如何运行')
    table(['阶段','输入与处理','保存内容'],[
        ['准备','校验数据与配置，生成运行标识；创建全新的系统/轮次/案例目录。','环境、配置、数据、源码指纹'],
        ['隔离','私有 HOME、XDG 和智能体状态；共享已安装运行时，不共享案例记忆。','工作目录与会话 ID'],
        ['交互','按案例内顺序执行。新会话使用新 ID；逻辑天数明确写入提示。','原始提示、回应、耗时、错误'],
        ['观测','读取配置的记忆文件；规范化原生工具调用；读取指定真实产物。','记忆快照、工具轨迹、文件字节与散列'],
        ['落盘','单一写入器追加事件并 fsync；维护前序散列和 manifest。','evidence.jsonl 与链头'],
        ['判分','确定性规则逐项判断，宏平均并报告未知项。','scores.json、HTML、CSV、SVG'],
        ['复核','读取保存的证据重新计算，不调用智能体。','verify 结果与交付文件校验']],[55,275,155])
    para('并发粒度是完整案例，案例内步骤保持串行；标准集 jobs=4，挑战集 jobs=2。单独的写入器串行维护证据链。一个案例失败后，其余步骤保留为执行错误，其他案例继续；不会自动重试后只保留成功结果。')
    para('原生轨迹：OpenClaw 从隔离目录的 SQLite transcript_events 按会话与新增序号读取，支持有界 Zstandard 解压，并配对 toolCall / toolResult；Hermes 读取 stream-json 的 tool_use。文件操作保留原生名称与参数，再规范化路径。')

    page('04 / DATA','标准集：覆盖六类记忆行为')
    table(['维度','场景与对照','案例 / 单系统单轮验证项'],[
        ['长期保持','稳定偏好写入、多个无关会话、模拟 7/30/90 天召回','6 / 18'],
        ['记忆调用','同项目多字段检索；从未提供字段必须拒绝猜测','6 / 12'],
        ['动态更新','旧值、更正、召回、删除、删除后再查询','6 / 24'],
        ['相近区分','相近项目名与相同字段，分别查询防止串扰','6 / 12'],
        ['边界识别','临时值、虚构敏感值、不可信引文；保留稳定正例','6 / 24'],
        ['任务复用','按历史路径和格式实际写入文件，验证工具与字节','6 / 18']],[75,305,105])
    para('固定种子 2026，六组实例变体，每个案例独立；共 168 个步骤。值使用合成编号，避免仅凭常识猜中。三种离线规则基线用于检查判分器能否区分能力，不参与真实系统排名。')
    para('标准集适合接口回归与基本能力定位，但同模板变体之间存在相关性。增加变体数不等于增加自然语言分布或独立任务类型；因此另设挑战集，并分别报告，不简单混成一个更大的总分。')

    page('05 / CHALLENGES','挑战集：检验迁移到更复杂的语义')
    rows=[]
    for case in challenge[1]: rows.append([DIMENSIONS[case['dimension']],case['title'],str(len(case['steps']))])
    table(['维度','独立挑战场景','步骤'],rows,[75,370,40])
    para('挑战集种子 7331，共 12 个独立语义模板、27 个验证项。重点是跨消息关联、否定约束、条件检索、局部更新、临时例外到期、版本/身份消歧、注入抵抗及真实文件任务。','small')
    para('这些题仍遵循可判定输出契约。答案通过结构化值或实际文件验证；不使用另一个模型作为裁判。模板公开，因此这是可复现实验集，不是秘密测试集。可用 generate --suite challenge --seed N 更换事实实例。','small')

    page('06 / SCORING','把得分和可观测性一起报告')
    table(['状态','解释','处理'],[
        ['pass','证据支持预期行为','计入通过与已判定分母'],['fail','证据明确否定预期行为','计入失败与已判定分母'],
        ['unknown','所需信息不可观察或快照不完整','留在总分母，呈现上下界'],['error','进程、协议或工具执行失败','单列工程错误，不冒充能力结论']],[75,270,140])
    para('设验证总权重 T，通过 P，失败 F，未知和错误合计 U，则 T=P+F+U。已观测分=P/(P+F)，证据覆盖率=(P+F)/T，下界=P/T，上界=(P+U)/T。先在案例内加权，再在维度内对案例与轮次等权平均，最后在有案例的维度间等权平均。')
    para('例如 P=2、F=1、U=1：已观测分 66.67%，覆盖率 75%，得分区间为 50%-75%。不能把 66.67% 单独作为完整能力成绩。这里的上下界来自缺失证据，并非统计置信区间。')
    para('严格 JSON 值和类型防止把字符串 null 当成空值；实际文件按路径及内容验证，口头声称写入不能通过。部分记忆快照中看不到禁存值时记为 unknown，看到禁存值则足以判 fail。已记录失败的工具调用不能通过动作检查。')
    para('五类记忆错误：遗漏、混淆、旧记忆复用、错误持久化、错误任务复用。另列输出格式错误与执行错误。三轮标准差描述本次重复稳定性，不代表总体统计置信度。')

    for number,title,run in [('07','标准集实测',core),('08','挑战集实测（标注订正后）',challenge)]:
        manifest,cases,events,scores=run
        page(number+' / RESULTS',title,f'运行 {manifest["run_id"]} · {len(cases)} 案例 · 三轮重复 · {len(events)} 个事件')
        agents=scores['agents']
        table(['系统','已观测分','覆盖率','下界 / 上界','三轮标准差'],[[a['id'],pct(a['overall']['score']),pct(a['overall']['coverage']),pct(a['overall']['lower_bound'])+' / '+pct(a['overall']['upper_bound']),pct(a['stability']['stddev'])] for a in agents],[70,95,90,145,85])
        table(['能力维度']+[a['id']+' 下界 / 覆盖' for a in agents],[[label]+[pct(a['dimensions'][d]['lower_bound'])+' / '+pct(a['dimensions'][d]['coverage']) for a in agents] for d,label in DIMENSIONS.items()],[95,195,195])
        table(['系统','通过','失败','未知','错误','P50 / P95 秒'],[[a['id']]+[str(sum(c['statuses'].get(s,0) for c in a['cases'])) for s in ['pass','fail','unknown','error']]+[f'{a["runtime"]["latency_p50_ms"]/1000:.1f} / {a["runtime"]["latency_p95_ms"]/1000:.1f}'] for a in agents],[70,55,55,55,55,195])
        para('各系统使用相同模型名称、相同输出上限和温度设置，但智能体内部提示、工具和记忆机制不同。本结果评估系统组合，不能归因于单一记忆算法。延迟包含 CLI 启动、代理队列、网络和模型时间。标准集与挑战集的并发/超时配置不同，不比较跨集速度。','small')
        para('完整雷达图与逐项结果见对应 examples 目录；挑战集使用 reviewed-report.html；点击评分项可进入相应证据检查器，逐事件核对原始返回、文件和评分标准。','small')

    page('08B / ANNOTATION REVIEW','发现并修正评测器自己的误判')
    para('两系统在跨消息关联题中都正确回答松柏项目，原答案标注却只接受松柏，造成六次误判。这是标注缺陷，不是智能体记忆混淆。订正版显式接受这两个等价值，仍拒绝错误实体、多余解释和类型不符。')
    table(['系统','冻结原始下界','订正后下界','订正后上界'],[[a['id'],pct(a['overall']['lower_bound']),pct(b['overall']['lower_bound']),pct(b['overall']['upper_bound'])] for a,b in zip(challenge_raw[3]['agents'],challenge[3]['agents'])],[100,130,130,125])
    para('订正只改一个答案检查，对两款系统、三轮统一应用；其余 156 个检查和全部运行错误保持不变。既有提示、回答、记忆快照和文件证据没有重写，不发起新的付费调用。原始 report.html / scores.json 保留，订正结果另存 reviewed-report.html / reviewed-scores.json。')
    para('这是实测后公开的标注修订，不是预注册判分。scripts/review_challenge.py --check 从原始证据独立复算，断言只有六次 fail 变为 pass，并校验订正后的数据和分数。上页及后续图表明确采用订正值；原始与订正成绩在此并列。')
    para('这一发现说明高分或低分都应回到具体证据审查。扩展自由文本测试前，应显式定义等价答案或评分标准，避免把标注粒度问题包装成模型能力结论。')

    page('09 / VISUAL SUMMARY','六维结果的可视化复核')
    from reportlab.graphics.shapes import Drawing,Line,Polygon,String,Circle
    import math
    drawing=Drawing(485,320)
    palette=[green,colors.HexColor('#dc8840')]
    for cx,title,run in [(120,'标准集 / CORE',core),(365,'挑战集 / 订正后',challenge)]:
        cy=157;radius=80
        def point(index,fraction):
            angle=math.pi/2-index*math.pi/3
            return cx+radius*fraction*math.cos(angle),cy+radius*fraction*math.sin(angle)
        drawing.add(String(cx,288,title,fontName=font,fontSize=12,textAnchor='middle',fillColor=ink))
        for fraction in [.25,.5,.75,1]:
            coords=[value for i in range(6) for value in point(i,fraction)]
            drawing.add(Polygon(coords,fillColor=None,strokeColor=colors.HexColor('#d7e2dc'),strokeWidth=.6))
        for i,label in enumerate(DIMENSIONS.values()):
            x,y=point(i,1)
            drawing.add(Line(cx,cy,x,y,strokeColor=colors.HexColor('#d7e2dc'),strokeWidth=.6))
            x,y=point(i,1.27)
            drawing.add(String(x,y-3,label,fontName=font,fontSize=8,textAnchor='middle',fillColor=ink))
        for j,a in enumerate(run[3]['agents']):
            values=[a['dimensions'][d]['lower_bound'] or 0 for d in DIMENSIONS]
            coords=[value for i,v in enumerate(values) for value in point(i,v)]
            drawing.add(Polygon(coords,fillColor=None,strokeColor=palette[j],strokeWidth=1.8))
            for i,v in enumerate(values):
                x,y=point(i,v);drawing.add(Circle(x,y,2,fillColor=palette[j],strokeColor=None))
        for j,a in enumerate(run[3]['agents']):
            x=cx-76+j*88
            drawing.add(Line(x,20,x+13,20,strokeColor=palette[j],strokeWidth=2))
            drawing.add(String(x+18,17,a['id'],fontName=font,fontSize=8,fillColor=ink))
    story.append(drawing)
    para('半径从中心 0% 到外圈 100%，每条线绘制对应数据集的六维保守下界。两个数据集包含不同任务和证据要求，应分别解读，不将图形面积当作能力排名。','small')
    table(['数据集 / 系统','下界','上界','覆盖率','三轮标准差'],[
        [label+' / '+a['id'],pct(a['overall']['lower_bound']),pct(a['overall']['upper_bound']),pct(a['overall']['coverage']),pct(a['stability']['stddev'])]
        for label,run in [('标准集',core),('挑战集',challenge)] for a in run[3]['agents']
    ],[145,85,85,85,85])
    para('上下界来自未知与执行错误项的可观测性限制，不是统计置信区间。三轮标准差仅描述本配置下的重复波动，不支持显著性或通用排名结论。','small')

    page('10 / FINDINGS','失败与未知项如何解释')
    found=[]
    for name,run in [('标准集',core),('挑战集',challenge)]:
        m,cases,events,scores=run
        idx={e['event_id']:e for e in events}
        for a in scores['agents']:
            for case in a['cases']:
                for check in case['checks']:
                    if check['status']=='fail' and len(found)<4:
                        e=idx[check['evidence_id']]
                        found.append([name+' / '+a['id'],case['title']+' / '+check['check_id'],check['category'],e['event_id']])
    if found: table(['数据 / 系统','未通过项目','错误类别','事件'],found,[105,215,115,50])
    else: para('本次所有可观测验证项均通过。这个结果只说明公开合成集在本配置下未发现可判定失败；不应据此推断自然用户任务已被完全解决。')
    execution_errors=sum(run[0]['execution_errors'] for run in runs)
    para(f'本次两套实验记录 {execution_errors} 个执行错误事件（包含某案例前序失败后被跳过的步骤）。错误保留在原始证据和分母中，不用单案例重跑覆盖。网络请求失败与能力失败分开解释；对应审计事件见 api-audit.jsonl 和 experiment.json。')
    para('未知项需要与能力失败分开：原生适配器默认只观察声明的记忆文件。即使文件中没有被撤销的值，也不能证明所有日志、索引或远端存储都已删除。标准集保留这些 unknown，以得分上下界显示这一测量限制。')
    para('核验步骤：打开失败项的事件链接，先对照提示和严格输出格式，再检查记忆快照与文件。如果是格式不符，定位 invalid_response；如果新值被旧值取代，定位 stale_memory；如果只有文件口头声明而无实际文件，定位 wrong_reuse。')
    para('挑战集另有一次 OpenClaw 重复工具读取触发预算保护，连同后续跳过共两个执行错误事件。详情与原生轨迹摘要见 docs/evidence/challenge-resource-guard.json；未用单例重试覆盖。','small')
    para('挑战集侧重行为输出和实际产物，与标准集的存储验证范围不同。两个数据集的总分不可直接当作同一个量纲比较；应先看同一数据集内的维度、覆盖率和具体案例。')

    if core[0]['run_id']=='dc318856-004f-4b1c-9910-2ab94d6b2633':
        page('11 / CASE STUDIES','三个失败，三种不同的解释')
        para('以下案例直接来自本次标准集的原始事件；完整提示、回应和快照可在 evidence.html 按事件编号查看。','small')
        para('01  新项目被误当作旧项目的修订','h2')
        para('Hermes 第一轮，事件 28 保存星河项目的格式。事件 30 收到星河归档项目的不同约定后，明确回复已替换此前记录；快照只剩归档项目。事件 34 查询原项目时，返回了归档项目的值。')
        para('这组证据把问题定位到作用域混淆与错误替换，不只是最终回答错误。它评估该系统组合，不能单独归因于某种数据库或检索算法。','small')
        para('02  二次确认使撤销操作没有发生','h2')
        para('Hermes 第三轮，事件 920 将明确的删除请求转为选择删除方案，并说明尚未修改记忆。可见快照仍包含原值，事件 921 又返回同一值。两个检查分别记录错误持久化和旧记忆复用。')
        para('判分描述当前一次性撤销契约未完成。若产品必须二次确认，应预先为所有系统增加一致的确认协议，不能事后只为一个系统删掉检查。','small')
        para('03  记忆判断正确，输出格式仍失败','h2')
        para('OpenClaw 第一轮，事件 252 的可见记忆只剩项目标题；事件 257 返回正确的 null，但在 JSON 前增加英语解释。由于任务要求仅输出 JSON，该项按 invalid_response 失败。')
        para('这是接口契约失败，不证明旧值仍被记住。全局删除仍为 unknown，因为部分文件快照无法证明所有存储都已删除。详细案例见 docs/case-studies.md。','small')

    page('12 / REPRODUCIBILITY','固定环境、固定材料、独立复核')
    table(['项目','实测配置'],[
        ['系统',core[0]['environment']['os_release']['PRETTY_NAME']+' / WSL 2'],
        ['内核',core[0]['environment']['release']],['框架 Python',core[0]['environment']['python']],
        ['OpenClaw','2026.9.8 / fc23bc8'],['Hermes','4b8a43719b2a259cea88a72f9f13a2b6962e7ac3'],
        ['模型与推理控制','deepseek-flash；thinking disabled；temperature 0；max_tokens <= 2048'],
        ['实验策略','两系统各三轮；标准集 jobs=4，挑战集 jobs=2；不选择性重试'],
        ['工具策略','Hermes file/memory 工具，max_turns=6；OpenClaw read/write/edit/memory_search/memory_get，未另启用 loopDetection'],
        ['依赖复用','复用本机 Ubuntu 已安装的运行时；openKylin 原生 Python；不共享案例记忆'],
        ['安装验证','见交付包 validation/package-lifecycle.log 的安装、运行、卸载和重新安装记录']],[105,380])
    para('收费调用经过本地代理。真实密钥只由代理读取，智能体拿到的是短期本地令牌。每次请求预留保守费用，并检查真实账户余额；保存模型返回的 token 用量及请求指纹。账户余额变化有结算延迟，费用分析区分实际查询值与保守估算。')
    para('冻结标准集代理存在一项已公开的审计缺口：累计计数增加 2242 次上游返回，completion 日志为 2237 条，5 次差额与后置余额查询失败有关。交付版已先保存已付费结果和审计，再更新余额；原始实验不替换。usage 合计仅代表已记录请求，详细对账见 docs/evidence/core-api-accounting.json。','small')
    para('常用复核命令','h2')
    para('python3 verify-delivery.py<br/>cd source<br/>python3 -m kylin_memory_bench verify examples/openkylin-core<br/>python3 -m kylin_memory_bench verify examples/openkylin-challenge<br/>python3 -m kylin_memory_bench demo --output runs/new-demo','small')
    para('原始实验使用冻结源码。报告页面可由新版本重新渲染，但原始提示、事件、评分和 manifest 不重写；实验源码快照随材料保存，便于核对 implementation_sha256。','small')

    page('13 / LIMITS','有效性边界与后续扩展')
    table(['边界','对结论的影响','后续实验'],[
        ['合成、规模有限','不是自然用户分布抽样；同模板变体相关','独立任务作者、隐藏种子、真实脱敏会话与人工复核'],
        ['逻辑时间','7/30/90 天是明确的模拟标签','真实时间 TTL、断电恢复和长时后台清理'],
        ['部分存储可见','缺失禁存值无法证明全局删除','适配版本化存储导出和远端索引审计'],
        ['单模型服务','当前结论是两系统在同一模型下的表现','固定记忆实现后再比较多个模型'],
        ['三轮重复','只能描述当前样本的重复波动','更多独立场景与预注册统计方案'],
        ['WSL 2 桌面','不代表裸机驱动、登录管理和 openKylin 专用内核验证','专用虚拟机/实体机上的硬件与完整系统认证'],
        ['可信被测程序','目录隔离和散列不等于安全沙箱','独立容器/虚拟机与只读评测端隔离']],[90,195,200])
    para('本项目优先保证评价可核验、失败不丢失和未知不被美化。扩展自由文本任务时，应保留固定版本的标注、裁判校准与人工抽检，避免引入无法复现的主观打分。')

    page('13B / LUNA CALIBRATION','新增压力题：公开测量边界')
    para('2026-10-14 的独立 Luna 校题使用 8 条开发历史，四题族各低／高一条；每条 24 次学习，两款原生 Agent 各一轮，另设只给充分原始证据的 reader_only。集合与反馈题候选表为 16 项。它不是原 128 会话协议，不是盲测，也不与历史 DeepSeek 三轮混算。')
    luna=read_json(ROOT/'docs/evidence/luna-short24-candidates16-results.json')
    table(['系统','条件','计划','有效观测','内容正确','任务成功'],[[r['agent'],r['condition'],r['planned'],r['observed'],r['content_correct'],r['task_success']] for r in luna['groups']],[80,100,65,75,80,85])
    para('32 个案例全部结束，31 个正常结束、1 个原生 CLI 异常；416 个计划事件槽保留 1 个执行错误。reader_only 内容正确 11/16，未达到预声明 14/16 门槛。集合题读者也失败，不能把全部失分解释为遗忘。两款 memory 内容正确均为 1/8，单轮小样本不支持排名。')
    para('多跳与更新题在给齐原始证据时均可答，历史记忆条件有失败，是跨会话保存／检索／状态使用链路的诊断线索，不足以锁定内部算法。8 条序列化题面另由独立实现解算核对；公开最终观测可离线复算内容、格式和文件，但已去除私人工具轨迹，不是完整原生执行链的公开认证。')
    para('原难度试测只有 1/6 个家族达到预设效应门槛；这一结论保持不变。Memory Stress 160 条是离线题库规模，不是全量真实实验已完成。新增材料作为探索附录，正式主线仍是历史实验、失败定位和独立复核。','small')
    para('来源：docs/submission-readiness-20261014.md、docs/evidence/luna-short24-candidates16-results.json、scripts/replay_luna_short_pilot.py。Luna 与历史 DeepSeek 模型、运行系统和条件分别标明。','small')

    page('13C / DESKTOP DEMO','真正 openKylin 的双智能体演示验收')
    video=read_json(ROOT/'docs/evidence/openkylin-luna-video.json')
    para('评测框架与 OpenClaw／Hermes 原生 CLI 在 openKylin 2.0 SP1 用户空间／WSL 2 执行；Ubuntu 只提供模型转发和无状态嵌入服务，OAuth 不复制。原生运行时只读复用，案例工作区相互隔离。')
    table(['系统','已观测分','覆盖率','下界','上界'],[[r['agent']]+[pct(r['overall'][k]) for k in ('score','coverage','lower_bound','upper_bound')] for r in video['groups']],[85,100,100,100,100])
    para('固定六维各一例，两款各一轮：56 个计划事件全部正常结束，执行错误 0；151 次模型请求均完成，返回模型均为 gpt-5.6-luna。实际约 9 分 1 秒。正常结束不等于满分，未知与失分完整保留。')
    para('这是录制入口的执行验收，不是新排行榜；案例与公开标准集重叠，上游无强制输出额度，不与历史 DeepSeek 三轮或压力校题合并。正式视频必须在录像开始后，从 UKUI 终端启动新目录的评测，保留连续原片和等待耗时。保存结果回放不能冒充完整真实运行录屏。')
    para('来源：examples/openkylin-luna-video/；docs/openkylin-luna-video.md；完整操作和中文旁白／SRT 见 docs/recording-runbook.md。运行编号 '+video['run_id'],'small')

    page('14 / REFERENCES','参考依据与交付索引')
    refs=[
        ('赛题计划书','项目根目录 ai_open_kylin_open_kylin_benchmark_XaCQyZepC8.pdf，3 页。'),
        ('openKylin 官方 WSL 项目','https://gitee.com/openkylin/openkylin-wsl'),
        ('OpenClaw 官方仓库','https://github.com/openclaw/openclaw'),
        ('Hermes 官方仓库','https://github.com/NousResearch/hermes-agent'),
        ('DeepSeek API 文档','https://api-docs.deepseek.com/'),
        ('LongMemEval','https://arxiv.org/abs/2410.10813'),
        ('LoCoMo','https://arxiv.org/abs/2402.17753')]
    for i,(title,url) in enumerate(refs,1): para(f'[{i}] {esc(title)}<br/>{esc(url)}','small')
    para('研究定位：LongMemEval 讨论信息提取、多会话推理、时间推理、知识更新和拒答能力；LoCoMo 通过长对话评估问答、事件总结和多模态生成。本项目没有导入这些数据或复现其排行榜，主要补充面向 openKylin 原生智能体、实际工具与文件证据的工程评测路径。','small')
    table(['材料','入口'],[['交付总入口','START_HERE.md'],['标准实测与挑战实测','examples/openkylin-core/；examples/openkylin-challenge/'],['方法和适配协议','docs/design.md；docs/adapters.md；schemas/'],['目标系统与录屏','docs/openkylin.md；docs/demo-video.md'],['测试与安装证据','docs/validation.md；docs/evidence/'],['代码与安装包','source/；packages/；scripts/reproduce.*']],[125,360])
    para('数据指纹','h2')
    for name,run in [('CORE',core),('CHALLENGE ORIGINAL',challenge_raw),('CHALLENGE REVIEWED',challenge)]: para(name+' '+digest(run[1]),'small')
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    def decorate(c,doc):
        w,h=doc.pagesize
        c.setFillColor(green);c.rect(42,h-25,w-84,3,fill=1,stroke=0)
        c.setFont(font,8);c.setFillColor(muted);c.drawString(42,25,'Kylin Memory Bench / '+__version__+' / '+datetime.date.today().isoformat())
        c.drawRightString(w-42,25,str(doc.page))
    doc=SimpleDocTemplate(str(out),pagesize=(595.28,841.89),rightMargin=55,leftMargin=55,topMargin=51,bottomMargin=48,title='Kylin Memory Bench - 技术方案与实测报告',author='Kylin Memory Bench contributors')
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    print(out)

if __name__=='__main__': main()
