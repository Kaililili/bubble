"""受控词表(抽取提示词与归一化共用,单一来源)。"""

# 实体类型(与抽取提示词一致;normalizer 用它把模型输出收敛到白名单)
ENTITY_TYPES = (
    "sport", "league", "team", "person", "org", "work", "product",
    "place", "tech", "event", "topic", "other",
)

# 关系类型(专指到泛指 / 成员到组织 / 部分到整体 / 一般关联 / 共现)
RELATION_TYPES = ("broader", "related", "member_of", "part_of", "co_occur")
