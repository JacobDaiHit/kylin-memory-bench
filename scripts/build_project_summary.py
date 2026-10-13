"""Build an exactly two-page Chinese project summary; reportlab is authoring-only."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/project-summary.pdf')
    parser.add_argument('--font', type=Path, default=Path('/mnt/c/Windows/Fonts/simsun.ttc'))
    args = parser.parse_args()
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.utils import simpleSplit
    if args.font.is_file():
        pdfmetrics.registerFont(TTFont('SummaryCJK', str(args.font), subfontIndex=0))
    else:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    font = 'SummaryCJK' if args.font.is_file() else 'STSong-Light'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(args.output), pagesize=(595,842))
    pdf.setTitle('Kylin Memory Bench 0.2.1 — 两页项目摘要')
    def page(title, blocks, number):
        y = 785
        pdf.setFillColorRGB(.08,.24,.19)
        pdf.setFont(font,24)
        pdf.drawString(48,y,title)
        y -= 40
        for heading, text in blocks:
            pdf.setFont(font,13)
            pdf.drawString(48,y,heading)
            y -= 25
            pdf.setFont(font,10.5)
            # Chinese wrapping is explicit so the two-page contract is stable.
            lines, line = [], ''
            for char in text:
                if char == '\n': lines.append(line); line=''; continue
                if pdfmetrics.stringWidth(line+char,font,10.5)>495:
                    lines.append(line);line=''
                line += char
            if line:lines.append(line)
            for line in lines:
                pdf.drawString(48,y,line);y-=18
            y-=15
        if y < 65: raise ValueError('Summary text exceeds page')
        pdf.setFont(font,9)
        pdf.drawString(48,35,'Kylin Memory Bench / 0.2.1 / 2026-10-14')
        pdf.drawRightString(547,35,str(number))
        pdf.showPage()
    core=json.loads((ROOT/'examples/openkylin-core/scores.json').read_text())
    challenge=json.loads((ROOT/'examples/openkylin-challenge/reviewed-scores.json').read_text())
    def results(scores):
        return '；'.join(a['id']+'：已观测分 %.2f%%，覆盖率 %.2f%%'%(100*a['overall']['score'],100*a['overall']['coverage']) for a in scores['agents'])
    page('让智能体记忆表现有据可查',[
        ('项目目标','在明确任务与运行条件下，用可复核证据评估记忆表现，定位失败并说明观测边界。核心工具使用 Python 标准库，可离线运行，无需 GPU 或模型密钥。'),
        ('完整流程','版本化案例 → 原生 OpenClaw／Hermes → 新会话与独立工作区 → 回答、可见记忆、工具、真实文件 → 确定性评分 → HTML 六维图与逐事件证据 → 独立重放。'),
        ('六维与正式数据','长期保持、记忆调用、动态更新、相近区分、边界识别、任务复用。36 标准案例是六模板的事实变体；独立挑战集 12 案例。DeepSeek Flash 同模型，两款各三轮，openKylin 2.0 SP1 用户空间／WSL 2。'),
        ('历史标准集成绩',results(core)),
        ('历史挑战集订正成绩',results(challenge)+'。“松柏／松柏项目”合法别名订正公开，原分数和证据保留；不同数据集不混算排名。'),
        ('最有价值的失败案例','Hermes 的 #28 → #30 → #34 → #35：相近但不同的项目被当作同一条信息的修订。原项目回答错误，归档项目回答正确，可见记忆支持作用域混淆线索。')],1)
    page('交付、复核与诚实的测量边界',[
        ('新增压力题','30 条首期开发历史及四题族四档共 160 条离线场景。程序化状态 Oracle、充分原始证据对照、反事实检查、集合约束与反馈任务；离线规模不等于真实全量成绩。'),
        ('Luna 校题结论','8 条短历史、两款原生 Agent 各一轮，memory 与 reader_only 分开，共 32 案例。memory 两款各正确 1/8，Hermes 含 1 个执行错误；读者共正确 11/16，未达预设 14/16。集合题读者失败，不能把全部失分归为记忆。新增题保留探索定位，不宣称难度充分或稳定排名。'),
        ('评分与底座检查','30 条固定契约样例、4 组指标对照及新增负例检查；没有第三方独立人审。openKylin 无凭据、隔离网络复核原件、拒绝篡改；参考适配器验证跨进程保留和工作区隔离，不代表真实 Agent TTL 或全局删除。'),
        ('可获取的交付','源码、JSONL 数据、原生适配器、wheel、.deb、离线导览、技术报告、两页摘要、证据与源码快照、录制手册／旁白／字幕。最终 MP4 由提交者录制；具体安装验收以精确包散列和日志为准。'),
        ('接收者三步','打开 START_HERE.md；查看正式报告并下钻事件；执行 python3 verify-delivery.py。核心 demo 与证据复核不调用模型。原生新实验需安装运行时并配置自己的模型认证。'),
        ('维护与边界','github.com/JacobDaiHit/kylin-memory-bench，GitHub Issues 为公开维护入口。合成数据、模拟时间、部分存储可见性和 WSL 范围明确披露。散列链不是第三方可信执行证明；录制就绪不等于主办方已收件。')],2)
    pdf.save()
    print(args.output)


if __name__ == '__main__':
    main()
