# Enterprise Energy Research v0.9.0 API image: offline build, venv-free, non-root.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EER_AUTOMATION_DATABASE_URL=postgresql+psycopg://research:research@postgres:5432/research \
    EER_AUTOMATION_WORKDIR=/data/automation_work

WORKDIR /app

# Install system rendering dependencies before application sources so ordinary
# Python/HTML edits keep the large Chromium layer cached.
COPY pyproject.toml ./
# 中文字体用于 SVG 文本；Chromium 将与 HTML 完全相同的 diagram-design SVG 栅格化供 Word 嵌入。
# libcairo2-dev/gcc/pkg-config 供 pycairo（svglib→rlpycairo 传递依赖）源码编译，
# slim 镜像无编译器会 metadata-generation-failed；编译完成后仅保留运行时库。
RUN apt-get update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends chromium-headless-shell fonts-wqy-microhei \
        libcairo2-dev gcc pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 市场交付物 Stage 5/7/8：Excel 公式重算与 Word/PPT 渲染 QA 依赖 LibreOffice
# headless（soffice）；nogui 变体不引入 X11 依赖，镜像体积可控。
# fonts-noto-cjk 覆盖图表渲染的 CJK 字体候选表（同时含 Noto Sans/Serif CJK SC；
# Debian 无 fonts-noto-serif-cjk 独立包），仅有 WenQuanYi 时 common/fonts.py 会 RuntimeError。
RUN apt-get update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        libreoffice-core-nogui libreoffice-calc-nogui libreoffice-writer-nogui libreoffice-impress-nogui \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Copy package sources + config + embedded vendor skills (search/webbridge
# adapters resolve their runtimes from vendor/; without it they fail closed).
COPY src ./src
COPY config ./config
COPY vendor ./vendor

# api+database for the control plane; models enables the LLM gateway for
# real extraction (litellm). Install full for convenience on small images.
# 使用清华 PyPI 镜像加速国内构建；如需官方源删除 --index-url 参数即可。
RUN pip install --no-cache-dir \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    -e ".[api,database,models]"

# 内嵌海外市场研究 skill 的运行时依赖：采集/交付物子进程用镜像解释器直接
# import bs4/docx/pptx 等，缺依赖会秒级崩溃且上层无诊断。排除项：
# packaging——镜像已带更高版本，vendored 钉的 <26 会无谓降级；
# tomli——仅 py<3.11 需要，裸行会被 pip 当包名解析失败。
RUN grep -vE '^(packaging|tomli)' vendor/skills/overseas-energy-market-research/requirements.txt > /tmp/vendor-reqs.txt \
    && pip install --no-cache-dir \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        -r /tmp/vendor-reqs.txt \
    && rm /tmp/vendor-reqs.txt

# pycairo 已编译完成，移除编译工具链瘦身；pycairo 由 pip 安装，apt 不知道它
# 依赖 libcairo2，先手动标记避免 --auto-remove 误删运行时库。
RUN apt-mark manual libcairo2 \
    && apt-get purge -y --auto-remove gcc pkg-config libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data/automation_work && useradd -m -u 10001 research \
    && chown -R research:research /data/automation_work
USER research

EXPOSE 8000

CMD ["uvicorn", "enterprise_energy_research.automation.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
