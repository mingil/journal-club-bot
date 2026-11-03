# 🏥 의국 저널 클럽 봇 (Journal Club Bot - EBM Edition)

> 🌐 **Language**: [English](./README.md) | **한국어**

[![Docker Image CI](https://github.com/mingil/journal-club-bot/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/mingil/journal-club-bot/actions/workflows/docker-publish.yml)
[![Docker Hub](https://img.shields.io/docker/v/kimmingil/journal-club-bot?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/kimmingil/journal-club-bot)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

> **PubMed 최신 임상 논문(RCT) 자동 수집 · Google Gemini 시니어 교수 페르소나 비판적 분석 · Zotero 서지 관리 · Notion 아카이빙 · 의국 단체 이메일 브리핑까지 100% 자동화하는 올인원 Docker 봇**

---

## ✨ 왜 이 봇이 필요한가요?

매주 돌아오는 의국 저널 클럽(Journal Club) 발표를 위해 수많은 저널을 일일이 검색하고, 임상과 무관한 기초/타 직군 논문을 걸러내며, 서지 프로그램(Zotero)과 노션(Notion)에 정리하는 반복 작업을 완전히 자동화합니다.

### 🌟 6대 핵심 기능
1. **🎯 정밀한 임상의(MD) 주도 RCT 논문 필터링 (`fetcher_md.py`)**
   - 지정된 핵심 타겟 저널에서 최신 무작위 대조군 연구(RCT)만 1차 추출합니다.
   - 제1저자 또는 교신저자의 소속(Affiliation)과 학위(MD/DO/MBBS)를 정규식 3단계 필터(전공 키워드 + 의료기관 화이트리스트 + 기초/타 직군 네거티브 필터)로 정밀 검증하여 실제 진료 현장의 의사 주도 논문만 골라냅니다.
2. **🤖 Google Gemini 시니어 교수의 날카로운 EBM 비판적 분석 (`analyzer.py`)**
   - 단순 번역이나 요약이 아닙니다. 근거중심의학(EBM)에 정통한 **의과대학 시니어 교수 페르소나**가 논문의 한 줄 평, 저자 전문성 팩트 체크, **PICO 분석**, **연구 디자인의 치명적 한계(N수, 맹검, 편향)**, **실제 외래/치료실 적용 가능성(MCID, 수가/장비 제약)**을 냉철하게 브리핑합니다.
3. **⚡ Zotero 로컬 캐싱(0.01초) & 순정 메타데이터 업로드 (`zotero_manager.py`)**
   - 의국 공유 Zotero의 `후보(Candidates)` 및 `발표 완료(Presented)` 두 폴더를 대조하여 **한 번 처리된 논문(PMID/DOI)은 영구적으로 중복 수집을 차단**합니다.
   - 로컬 JSON 캐시(`config/zotero_cache.json`)를 통해 평소에는 API 호출 없이 0.01초 만에 중복을 판별하며, 주간/월간 백업 스캔 시 Zotero 서버와 자동 동기화합니다.
4. **📝 Notion 대시보드 자동 디자인 아카이빙 (`notion_manager.py`)**
   - 한/영 노션 데이터베이스 제목 컬럼(`이름`, `Name`, `Title`)을 자동으로 인식(Zero-Config)합니다.
   - 메타데이터 콜아웃 박스, PubMed 북마크, 영문 초록 접기(Toggle) 블록, 영역별 컬러 콜아웃 박스로 시각화된 브리핑 카드를 자동 생성합니다.
5. **📧 모바일/PC 반응형 HTML 단체 이메일 리포트 (`notifier.py`)**
   - 클릭 가능한 상단 목차(TOC), MD 확실성 뱃지, 컬러풀한 브리핑 박스, PubMed 원문 바로가기 버튼이 포함된 깔끔한 HTML 뉴스레터를 의국원 전체에게 발송합니다.
6. **🛡️ 3중 안전망 스케줄러 & 무중단 에러 격리 (`main.py`)**
   - **매일(07:00, 최근 7일) · 매주 일요일(07:10, 최근 30일) · 매월 첫째 주 월요일(07:20, 최근 90일)** 3중 겹침 스캔으로 PubMed 인덱싱 지연으로 인한 누락을 0%로 방어합니다.

---

## 🚀 빠른 시작 가이드 (Quick Start)

### 방법 A. Docker Hub 공식 이미지로 즉시 실행하기 (권장)

1. 작업 폴더를 만들고 이동합니다:
   ```bash
   mkdir -p journal-club-bot/config journal-club-bot/logs
   cd journal-club-bot
   ```
2. 아래 내용으로 `compose.yaml` 파일을 만듭니다:
   ```yaml
   services:
     journal-club-bot:
       image: kimmingil/journal-club-bot:latest
       container_name: journal-club-bot
       restart: unless-stopped
       env_file:
         - .env
       environment:
         - TZ=Asia/Seoul
         - PYTHONUNBUFFERED=1
       volumes:
         - ./config:/app/config
         - ./logs:/app/logs
   ```
3. `.env.example`을 참고하여 `.env` 파일을 만들고 API 키를 입력합니다.
4. `config/settings.yaml`에 원하는 타겟 저널 목록을 넣습니다.
5. 컨테이너를 실행합니다:
   ```bash
   docker compose up -d
   ```

### 방법 B. GitHub 저장소 복제 후 직접 빌드하기

```bash
git clone https://github.com/mingil/journal-club-bot.git
cd journal-club-bot
cp .env.example .env
docker compose up -d --build
```
