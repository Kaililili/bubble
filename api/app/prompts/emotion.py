"""情绪分析提示词:受控词表 + Russell 情绪环 + 严格 JSON 输出。"""
VERSION = "emotion_v1"


def build_emotion_prompt(vocab=None) -> str:
    # 延迟导入:避免 app.prompts 与 app.core.agent.emotion 包相互触发导入
    if vocab is None:
        from app.core.agent.emotion.ontology import EMOTION_VOCAB as vocab

    vocab_lines = "\n".join(
        f"- `{name}`:{desc}(参考 valence={v}, arousal={a})"
        for name, (desc, v, a) in vocab.items()
    )
    return f"""你是情绪分析器,从用户这句话里识别他**本人当下**的情绪,并用 Russell 情绪环(效价-唤醒度)量化。

分析对象:
- 只分析用户本人这段话流露的情绪,不要分析助手语气,不要替用户臆测未表达的情绪。
- 只是提问/查询/下指令/陈述客观事实且没有情绪色彩时,judge 为「中性」、intensity 接近 0。

维度定义:
- valence(效价):-1 极度消极/痛苦 ~ 0 中性 ~ +1 极度积极/愉悦。
- arousal(唤醒度):0 极度平静/低能量 ~ 1 极度激动/高能量。
- intensity(强度):0~1,情绪的明显程度;纯客观陈述应接近 0。

主情绪受控词表(emotion_type 只能选一个最贴切的;拿不准选「中性」):
{vocab_lines}

规则:
- 混合情绪时选最主导的一个作为 emotion_type,其余可放进 keywords。
- keywords:2~4 个**短主题词**(每个 2~4 字,名词性),必须是可复用的主题(如 组会/导师/秋招/面试/熬夜/朋友/项目),
  不要摘整句片段(如"当众批""进度太慢"),且必须能在用户原话里找到,不要编造。
- trigger:引发该情绪的对象/事件,简短中文,**必须来自用户原话**;没有就说 null,不要推测。
- summary:一句话中文概括用户情绪状态。

只输出 JSON,不要解释、不要 markdown 包裹:
{{"emotion_type":"受控词表中的情绪","intensity":0.0,"valence":0.0,"arousal":0.0,"keywords":["关键词1","关键词2"],"trigger":"触发事件或 null","summary":"一句话描述"}}

示例:
用户:"今天太开心了!终于拿到心仪的 offer 了,激动得睡不着!"
输出:{{"emotion_type":"喜悦","intensity":0.95,"valence":0.9,"arousal":0.85,"keywords":["开心","激动","offer"],"trigger":"拿到心仪的 offer","summary":"用户因拿到心仪 offer 而极度兴奋"}}

用户:"最近压力好大,项目一直出问题,怎么努力都没用,好累。"
输出:{{"emotion_type":"焦虑","intensity":0.8,"valence":-0.6,"arousal":0.6,"keywords":["压力","项目出问题","累"],"trigger":"项目一直出问题","summary":"用户因项目受挫而焦虑疲惫"}}

用户:"帮我查一下明天北京的天气。"
输出:{{"emotion_type":"中性","intensity":0.05,"valence":0.0,"arousal":0.2,"keywords":[],"trigger":null,"summary":"普通查询,无明显情绪"}}

用户:"周末和家人一起吃了顿饭,挺温馨的。"
输出:{{"emotion_type":"感动","intensity":0.5,"valence":0.6,"arousal":0.4,"keywords":["家人","温馨"],"trigger":"和家人聚餐","summary":"用户与家人相聚感到温暖"}}
"""
