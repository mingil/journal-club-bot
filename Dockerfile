FROM python:3.11-slim

LABEL org.opencontainers.image.title="Journal Club Bot (Rehab-Med EBM Edition)"
LABEL org.opencontainers.image.description="Automated PubMed RCT Fetcher, Gemini AI Critical Appraisal, Zotero & Notion Archiving, and Email Reporter for Medical Journal Clubs"
LABEL org.opencontainers.image.licenses="MIT"

# ⏰ 타임존(KST) 및 파이썬 런타임 최적화 환경변수 설정
ENV TZ=Asia/Seoul \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY config/ ./config/
COPY src/ ./src/
RUN mkdir -p /app/logs

# 🩺 컨테이너 프로세스 생존 확인 (Synology Container Manager / Portainer 연동)
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD grep -q "main.py" /proc/1/cmdline || exit 1

CMD ["python", "src/main.py"]
