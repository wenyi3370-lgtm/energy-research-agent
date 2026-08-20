# research-api image (Phase 15): offline build, venv-free, non-root.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EER_AUTOMATION_DATABASE_URL=postgresql+psycopg://research:research@postgres:5432/research \
    EER_AUTOMATION_WORKDIR=/data/automation_work

WORKDIR /app

# Copy package sources + config + embedded vendor skills (search/webbridge
# adapters resolve their runtimes from vendor/; without it they fail closed).
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
COPY vendor ./vendor

# api+database for the control plane; models enables the LLM gateway for
# real extraction (litellm). Install full for convenience on small images.
# 使用清华 PyPI 镜像加速国内构建；如需官方源删除 --index-url 参数即可。
# 中文字体（文泉驿微米黑）：图表 PNG 渲染必需，否则中文全部变成方块。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    -e ".[api,database,models]"

RUN mkdir -p /data/automation_work && useradd -m -u 10001 research \
    && chown -R research:research /data/automation_work
USER research

EXPOSE 8000

CMD ["uvicorn", "enterprise_energy_research.automation.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
