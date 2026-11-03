import sys
import os
import time
import signal
import schedule
import yaml
import datetime
import logging
from logging.handlers import RotatingFileHandler

# 커스텀 모듈 임포트
from fetcher_md import MDFetcher
from zotero_manager import ZoteroManager
from notion_manager import NotionManager
from analyzer import PaperAnalyzer
from notifier import EmailNotifier

# --- 🛑 1. 도커 안전 종료 (Graceful Shutdown) 설정 ---
is_running = True

def handle_shutdown(signum, frame):
    global is_running
    logger.info("\n🛑 시스템 종료 신호 수신. 현재 진행 중인 작업까지만 안전하게 마치고 종료합니다...")
    is_running = False

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

# --- 📝 2. 로깅 및 경로 설정 (Docker 환경 최적화) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
logs_dir = os.path.join(project_root, "logs")
os.makedirs(logs_dir, exist_ok=True)

logger = logging.getLogger("JCBot")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

# 핸들러 중복 추가 방지
if not logger.handlers:
    # 파일 출력 (순환 로그로 무한 용량 증가 방지)
    file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "system.log"), maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 도커 UI 터미널 출력
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


def run_research_task(mode_name, days_back):
    logger.info("=" * 60)
    logger.info(f"🚀 [{mode_name}] 의국 저널클럽 봇 파이프라인 가동 (탐색 기간: 과거 {days_back}일)")
    logger.info("=" * 60)

    try:
        # [STEP 1] 설정 파일 로드 (한글 깨짐 방지 utf-8 강제)
        config_path = os.path.join(project_root, "config", "settings.yaml")
        if not os.path.exists(config_path):
            logger.error(f"❌ 설정 파일({config_path})이 없습니다. 실행을 중단합니다.")
            return

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        journals = config.get("target_journals", [])
        if not journals:
            logger.error("❌ settings.yaml에 타겟 저널(target_journals)이 설정되어 있지 않습니다.")
            return

        # 모듈 인스턴스화 (커스텀 필터/페르소나 설정 지원, 기본값은 기존 재활의학과 세팅 100% 유지)
        bot_email = os.environ.get("EMAIL", "dr.research@hospital.ac.kr")
        filter_config = config.get("filter_options", None)
        custom_persona = config.get("custom_persona", None)

        fetcher = MDFetcher(bot_email, filter_config=filter_config)
        zotero_mgr = ZoteroManager()
        notion_mgr = NotionManager()
        analyzer = PaperAnalyzer(custom_persona=custom_persona)
        notifier = EmailNotifier()

        # [STEP 2] Zotero에서 이미 처리된 논문(DOI/PMID) 목록 가져오기 (Source of Truth)
        # 주간/월간 백업 스캔 시에는 Zotero 서버와 로컬 캐시를 정기 동기화하여 정합성 100% 유지
        force_refresh = mode_name in ("Weekly_Backup", "Monthly_DeepScan")
        existing_ids = zotero_mgr.get_existing_identifiers(force_refresh=force_refresh)

        # [STEP 3] PubMed 타겟 저널 검색 (엄격한 MD & RCT 필터링 적용)
        papers = fetcher.fetch_recent_papers(journals, days_back)

        # [STEP 4] 신규 논문 100% 필터링 (완벽한 중복 방어)
        new_papers = []
        for p in papers:
            pmid = str(p.get("id", "")).strip()
            # DOI 정규화 (URL 찌꺼기 제거)
            doi_lower = str(p.get("doi", "")).lower().replace('https://doi.org/', '').replace('http://dx.doi.org/', '').strip()

            # PMID나 DOI 중 하나라도 Zotero DB에 있다면 스킵
            if (pmid and pmid in existing_ids) or (doi_lower and doi_lower in existing_ids):
                continue
            new_papers.append(p)

        logger.info(f"📊 PubMed 수집 완료: 중복을 제외한 최종 '신규 논문' {len(new_papers)}건 발견")

        if not new_papers:
            logger.info(f"💤 [{mode_name}] 새로 업데이트된 논문이 없어 대기 모드로 돌아갑니다.")
            return

        # [STEP 5] 🤖 개별 논문 AI 분석 및 각 플랫폼 업로드 (에러 격리망 적용)
        analysis_results = []
        success_count = 0

        for i, paper in enumerate(new_papers, 1):
            if not is_running:
                logger.warning("🛑 봇 종료가 예약되어 남은 논문 처리를 중단합니다.")
                break

            logger.info(f"▶ 처리 중 ({i}/{len(new_papers)}): {paper['title'][:50]}...")

            # 🛡️ 개별 논문 처리용 Try-Except (하나가 실패해도 봇이 죽지 않도록 방어)
            try:
                # 1) AI 비판적 분석 (순수 PICO 및 교수 코멘트)
                analysis_text = analyzer.analyze(paper)

                # 2) 🚀 Zotero 순정 메타데이터 업로드 (로컬 캐시 자동 갱신)
                z_ok = zotero_mgr.add_paper_to_candidates(paper, analysis_text=analysis_text)

                # 3) Notion에 보기 좋은 대시보드 카드 생성
                n_ok = notion_mgr.upload_paper(paper, analysis_text)

                if not z_ok and not n_ok and (zotero_mgr.zot or notion_mgr.notion):
                    raise RuntimeError("Zotero 및 Notion 업로드가 모두 실패했습니다.")

                # 4) 리포트 메일 발송용 데이터 저장
                analysis_results.append({"paper": paper, "analysis": analysis_text})
                success_count += 1

                # API 과부하 방지를 위한 안전한 휴식
                time.sleep(3)

            except Exception as inner_e:
                logger.error(f"⚠️ 개별 논문 처리 실패 (PMID: {paper.get('id', 'Unknown')}): {inner_e}")
                continue # 실패해도 뻗지 않고 다음 논문으로 무조건 넘어감

        # [STEP 6] 최종 이메일 리포트 의국 단체 발송
        # 🚨 [최적화] 대규모 싹쓸이 시 수백 건의 이메일 폭탄을 막기 위한 안전장치
        if analysis_results and is_running:
            if mode_name == "Manual_Mass_Sweep":
                logger.info("ℹ️ [알림] 대규모 싹쓸이 모드이므로 단체 이메일 발송(이메일 폭탄)은 생략합니다.")
            else:
                logger.info("📧 처리 완료된 신규 논문 리포트를 이메일로 발송합니다...")
                notifier.send_report(analysis_results)

        logger.info(f"✨ [{mode_name}] 전체 파이프라인 작업 완료! (성공: {success_count}/{len(new_papers)}건)")

    except Exception as e:
        logger.error(f"❌ [{mode_name}] 파이프라인 메인 치명적 오류: {e}", exc_info=True)


# --- 📅 3. 스케줄러 래퍼 함수 (안전망) ---
def job_daily():
    # 매일: 최근 7일(일주일) 치 스캔 (인덱싱 지연 방어용 겹침 스캔)
    run_research_task("Daily_Sync", 7)

def job_weekly():
    # 매주 (일요일): 최근 30일(한 달) 치 백업 스캔
    run_research_task("Weekly_Backup", 30)

def job_monthly():
    # 매월 (첫째 주 월요일 등): 최근 90일(세 달) 치 딥 스캔
    today = datetime.date.today()
    if 1 <= today.day <= 7:
        run_research_task("Monthly_DeepScan", 90)


if __name__ == "__main__":
    logger.info("🏥 [Dr.Research JC Bot V7.2] 시스템 구동 시작 (Rehab-Med EBM Edition)")

    # =====================================================================
    # 🚨 [수동 대규모 싹쓸이 (Mass Sweep) 설정] 🚨
    # 과거 논문을 한꺼번에 수집하고 싶을 때 아래 줄의 맨 앞 주석(#)을 지우거나,
    # 환경변수 MASS_SWEEP_DAYS에 일수를 지정하세요.
    # =====================================================================

    #run_research_task("Manual_Mass_Sweep", 450)  # 👈 필요할 때만 맨 앞의 '#'을 지우고 실행!
    mass_sweep_days = os.environ.get("MASS_SWEEP_DAYS", "").strip()
    if mass_sweep_days.isdigit() and int(mass_sweep_days) > 0:
        run_research_task("Manual_Mass_Sweep", int(mass_sweep_days))

    # =====================================================================

    # ⏩ 평시 모드: 봇 재시작 누락분 캐치를 위해 스케줄러가 돌기 전 최근 5일 치를 빠르게 스캔합니다.
    # (위에서 싹쓸이를 켰더라도 중복은 Zotero가 완벽히 차단하므로 켜두셔도 무방합니다.)
    run_research_task("Startup_Check", 5)

    # ⏰ 정규 스케줄 시간 설정 (환경변수로 변경 가능, 기본값 07:00 / 07:10 / 07:20)
    daily_time = os.environ.get("SCHEDULE_DAILY_TIME", "07:00")
    weekly_time = os.environ.get("SCHEDULE_WEEKLY_TIME", "07:10")
    monthly_time = os.environ.get("SCHEDULE_MONTHLY_TIME", "07:20")

    schedule.every().day.at(daily_time).do(job_daily)
    schedule.every().sunday.at(weekly_time).do(job_weekly)
    schedule.every().monday.at(monthly_time).do(job_monthly)

    logger.info(f"⏳ 스케줄러 가동 중... (매일 {daily_time} / 일요일 {weekly_time} / 첫째주 월요일 {monthly_time})")

    # 24/365 백그라운드 대기 루프
    while is_running:
        try:
            schedule.run_pending()
            time.sleep(10) # 1분보다 짧게 주어야 종료 신호(SIGTERM)에 10초 내로 반응합니다.
        except Exception as scheduler_e:
            logger.error(f"❌ 스케줄러 메인 루프 중 오류 발생: {scheduler_e}")
            time.sleep(60)

    logger.info("👋 봇 프로세스가 안전하게 종료되었습니다.")
