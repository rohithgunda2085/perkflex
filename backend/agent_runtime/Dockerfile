# Advisor runtime for Amazon Bedrock AgentCore (arm64). Build with backend/ as the context:
#   docker buildx build --platform linux/arm64 -f backend/agent_runtime/Dockerfile -t perkflex-advisor backend --load
FROM --platform=linux/arm64 python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/backend

COPY agent_runtime/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# The shared advisor code. No SQL, no certificates, no credentials: the runtime never touches the database.
COPY app ./app
COPY agent_runtime ./agent_runtime

RUN useradd --system --no-create-home --uid 10001 perkflex
USER perkflex

ENV ENVIRONMENT=production
EXPOSE 8080
CMD ["python", "-m", "agent_runtime.main"]
