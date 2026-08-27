from __future__ import annotations

from energy_research_agent.domain.models import ImageEvidence


class ImageSemanticRouter:
    """Route evidence images by explicit page context; never infer an entity match."""

    KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("logo", ("logo", "标识", "商标")),
        ("headquarters", ("总部", "总部大楼", "headquarters")),
        ("production_line", ("生产线", "产线", "assembly line")),
        ("workshop", ("车间", "厂房内部", "workshop")),
        ("factory", ("工厂", "厂区", "生产基地", "plant")),
        ("product_application", ("应用场景", "项目应用", "客户现场")),
        ("product", ("产品", "型号", "设备外观")),
        ("equipment", ("设备", "机组", "装置")),
        ("certificate", ("证书", "认证", "certificate")),
        ("project", ("项目现场", "工程项目", "交付项目")),
        ("office", ("办公室", "办公楼", "office")),
        ("location", ("园区", "区位", "地图")),
    )

    @classmethod
    def classify(cls, image: ImageEvidence) -> ImageEvidence:
        context = " ".join(filter(None, (image.alt_text, image.surrounding_text, image.source_title))).lower()
        for image_type, keywords in cls.KEYWORDS:
            if any(keyword.lower() in context for keyword in keywords):
                return image.model_copy(update={"image_type": image_type})
        return image.model_copy(update={"image_type": "other"})

    @classmethod
    def route(cls, images: list[ImageEvidence]) -> list[ImageEvidence]:
        return [cls.classify(image) for image in images]
