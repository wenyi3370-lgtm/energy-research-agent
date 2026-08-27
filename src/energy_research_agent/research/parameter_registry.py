"""ParameterInterpretationRegistry (P0-19).

Industry-specific parameter explanations (D50, 比表面积, 振实密度, 首次效率...)
must NOT be hardcoded in the generic publisher. An interpretation is emitted
only when (industry, parameter_name) matches a registered rule; otherwise the
publisher prints the parameter as-is without an industry commentary.
"""

from __future__ import annotations

# industry -> parameter_name -> explanation
INTERPRETATIONS: dict[str, dict[str, str]] = {
    "battery_material": {
        "D50": "D50反映颗粒粒径中位水平，是配方分散、涂布稳定性及倍率性能评估的基础输入",
        "比表面积": "比表面积会影响界面反应与首次不可逆容量，需结合客户电解液体系和极片设计验证",
        "振实密度": "振实密度关系到极片压实及体积能量密度，但不能脱离颗粒强度与循环膨胀单独判断",
        "首次效率": "首次效率影响首周锂损耗，应与补锂方案、正极匹配及客户测试方法共同核对",
    },
    "solar_module": {
        "转换效率": "转换效率为标称测试条件下的光电转换效率，实际发电量还受辐照、温度与遮挡影响",
        "温度系数": "温度系数描述功率随组件温度上升的衰减速率，是高温地区选型的关键参数",
    },
    "energy_storage": {
        "循环寿命": "循环寿命按标称充放电倍率与放电深度定义，实际寿命取决于运行工况与温控",
        "放电深度": "放电深度是每次循环允许放出的容量比例，与循环寿命和系统成本强相关",
    },
}


class ParameterInterpretationRegistry:
    """Resolve industry-specific parameter explanations; generic by default."""

    def __init__(self, rules: dict[str, dict[str, str]] | None = None) -> None:
        self.rules = rules or INTERPRETATIONS

    def interpretation(self, industry: str | None, product_category: str | None, parameter_name: str) -> str | None:
        if not industry:
            return None
        industry_rules = self.rules.get(industry) or {}
        if parameter_name in industry_rules:
            return industry_rules[parameter_name]
        if product_category and f"{product_category}.{parameter_name}" in industry_rules:
            return industry_rules[f"{product_category}.{parameter_name}"]
        return None
