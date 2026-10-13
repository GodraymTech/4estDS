"""树种代号与显示名称统一映射模块。

系统规范:
- 数据库 (tree_observations.species, runs.metrics_json 等) 及所有内部推理管线入库仅使用英文大写代码 (如 TREE, GG, QQ, HHL, THS, ML, BGR, WBHS)。
- 界面展示 (Web 前端、报告生成等) 自动将英文大写代码映射为对应中文。
"""
from __future__ import annotations

from typing import Mapping

#: 标准树种英文大写代码 -> 中文显示名称映射 (每个英文唯一对应一个中文)
SPECIES_CODE_TO_CN: dict[str, str] = {
    "QQ": "秋茄",
    "HHL": "红海榄",
    "THS": "桐花树",
    "ML": "木榄",
    "BGR": "白骨壤",
    "WBHS": "无瓣海桑",
    "TREE": "红树",
    "GG": "枯木",
}

#: 中文树种别名/全称 -> 标准英文大写代码映射
SPECIES_CN_TO_CODE: dict[str, str] = {
    "秋茄": "QQ",
    "红海榄": "HHL",
    "桐花树": "THS",
    "木榄": "ML",
    "白骨壤": "BGR",
    "无瓣海桑": "WBHS",
    "红树": "TREE",
    "其他红树": "TREE",
    "枯木": "GG",
    "死树": "GG",
}


def normalize_species_code(value: str | None, *, default: str = "") -> str:
    """将任意树种字符串归一化为数据库合法且唯一的英文大写代码。
    
    规则:
    1. 若已有中文映射 (如 '红树', '秋茄')，转换为对应标准大写英文 (如 'TREE', 'QQ')。
    2. 若为英文或其他自定义代号 (如 'DD', 'dd')，转换为纯大写 (如 'DD')，保留复核添加新树种的多样性，绝不强制兜底为 TREE。
    3. 若输入为空 (None 或空白字符)，返回指定的 default (默认为空字符串 '')，不可擅自强制修改为 TREE。
    
    Examples:
        >>> normalize_species_code("秋茄")
        'QQ'
        >>> normalize_species_code("qq")
        'QQ'
        >>> normalize_species_code("DD")
        'DD'
        >>> normalize_species_code("dd")
        'DD'
        >>> normalize_species_code("tree")
        'TREE'
        >>> normalize_species_code("枯木")
        'GG'
        >>> normalize_species_code("")
        ''
    """
    if not value or not str(value).strip():
        return default
    s = str(value).strip()
    if s in SPECIES_CN_TO_CODE:
        return SPECIES_CN_TO_CODE[s]
    return s.upper()


def get_species_display_name(
    value: str | None,
    custom_map: Mapping[str, str] | None = None,
    *,
    default: str = "未知树种",
) -> str:
    """获取树种的中文展示名称。
    
    规则:
    1. 每个英文代码唯一对应一个中文名称 (如 TREE 只能展示为 '红树')。
    2. 若输入为中文别名 (如 '其他红树', '红树')，规范化为其唯一中文展示名称。
    3. 若为新树种且无中文映射 (如 'DD')，保持大写英文代码原样展示 (如 'DD')。
    4. 仅当输入为空时返回 default (默认为 '未知树种')。
    
    Examples:
        >>> get_species_display_name("QQ")
        '秋茄'
        >>> get_species_display_name("TREE")
        '红树'
        >>> get_species_display_name("DD")
        'DD'
        >>> get_species_display_name("其他红树")
        '红树'
    """
    if not value or not str(value).strip():
        return default
    s = str(value).strip()
    if s in SPECIES_CN_TO_CODE:
        code = SPECIES_CN_TO_CODE[s]
        return SPECIES_CODE_TO_CN.get(code, s)
    code = normalize_species_code(s)
    if custom_map and code in custom_map:
        return custom_map[code]
    return SPECIES_CODE_TO_CN.get(code, code)
