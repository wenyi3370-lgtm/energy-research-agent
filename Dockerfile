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
# 中文字体用于 SVG 文本；Chromium 将与 HTML 完全相同的 Lieflat SVG 栅格化供 Word 嵌入。
RUN apt-get update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends chromium-headless-shell fonts-wqy-microhei \
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

RUN mkdir -p /data/automation_work && useradd -m -u 10001 research \
    && chown -R research:research /data/automation_work
USER research

EXPOSE 8000

CMD ["uvicorn", "enterprise_energy_research.automation.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
