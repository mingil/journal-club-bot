import sys
import os
import yaml
import time
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from dotenv import load_dotenv
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

# 🔥 [수정 1] 확성기(Logger) 이름을 "JCBot"으로 통합하여 모든 내부 모듈의 숨겨진 로그를 터미널로 강제 소환!
logger = logging.getLogger("JCBot")
logger.setLevel(logging.INFO)

if logger.hasHandlers():
    logger.handlers.clear() # 기존 핸들러 비우기

stream_handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("\n[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

from fetcher_md import MDFetcher
from zotero_manager import ZoteroManager
from notion_manager import NotionManager
from analyzer import PaperAnalyzer
from notifier import EmailNotifier

def run_manual(days_back=7, dry_run=False, no_email=False, force_sync=False):
    logger.info("=" * 70)
    logger.info(f"🚀 [수동 실행 모드] 의국 저널클럽 봇 가동 (최근 {days_back}일 스캔)")
    if dry_run:
        logger.info("⚠️ [DRY-RUN 모드] 업로드 및 메일 발송은 생략하지만 '로컬 캐싱 및 중복 검사'는 정상 수행합니다.")
    elif no_email:
        logger.info("ℹ️ [NO-EMAIL 모드] Zotero/Notion 업로드는 수행하고 이메일 발송만 생략합니다.")
    logger.info("=" * 70)

    try:
        config_path = os.path.join(project_root, "config", "settings.yaml")
        if not os.path.exists(config_path):
            logger.error(f"❌ 설정 파일이 없습니다. 경로를 확인해주세요: {config_path}")
            return

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        journals = config.get("target_journals", [])
        bot_email = os.environ.get("EMAIL", "dr.research@hospital.ac.kr")
        filter_config = config.get("filter_options", None)
        custom_persona = config.get("custom_persona", None)

        # 모듈 초기화
        fetcher = MDFetcher(bot_email, filter_config=filter_config)
        analyzer = PaperAnalyzer(custom_persona=custom_persona)

        # 🔥 [수정 2] Dry-Run 여부와 상관없이 ZoteroManager 무조건 가동!
        zotero_mgr = ZoteroManager()

        if not dry_run:
            notion_mgr = NotionManager()
            notifier = EmailNotifier()

        # 🔥 [수정 3] Dry-Run 모드라도 무조건 로컬 캐시를 읽고 중복을 거르도록 강제 수행!
        logger.info("🔍 [1/4] Zotero 로컬 캐시 확인 및 중복 검사 중...")
        existing_ids = zotero_mgr.get_existing_identifiers(force_refresh=force_sync)
        logger.info(f"✅ 조테로 동기화 통과 (총 {len(existing_ids)}건 방어벽 세팅 완료)")

        # PubMed 검색
        logger.info(f"🌐 [2/4] PubMed 검색 시작 (타겟 저널 {len(journals)}개, 과거 {days_back}일)...")
        papers = fetcher.fetch_recent_papers(journals, days_back)

        new_papers = []
        for p in papers:
            pmid = str(p.get("id", "")).strip()
            doi_lower = str(p.get("doi", "")).lower().replace('https://doi.org/', '').replace('http://dx.doi.org/', '').strip()

            if (pmid and pmid in existing_ids) or (doi_lower and doi_lower in existing_ids):
                continue
            new_papers.append(p)

        logger.info(f"📊 검색 완료! 처리할 '신규 논문' 총 {len(new_papers)}건 발견.")

        if not new_papers:
            logger.info("💤 처리할 신규 논문이 없어 수동 실행을 종료합니다.")
            return

        # AI 분석 시작
        logger.info("🤖 [3/4] AI 시니어 교수 분석 시작!")

        analysis_results = []
        success_count = 0

        for i, paper in enumerate(new_papers, 1):
            logger.info("-" * 70)
            logger.info(f"▶ 처리 중 ({i}/{len(new_papers)}): {paper.get('title', '')[:60]}...")

            try:
                # AI 분석 호출
                analysis_text = analyzer.analyze(paper)

                print("\n" + "✨"*25)
                print("         [ 🤖 AI 분석 결과 미리보기 ]")
                print("✨"*25)
                print(analysis_text)
                print("✨"*25 + "\n")

                if not dry_run:
                    logger.info("   💾 플랫폼 업로드 진행 중...")
                    z_success = zotero_mgr.add_paper_to_candidates(paper, analysis_text=analysis_text)
                    n_success = notion_mgr.upload_paper(paper, analysis_text)

                    logger.info(f"   -> Zotero: {'✅' if z_success else '❌'} | Notion: {'✅' if n_success else '❌'}")

                    analysis_results.append({"paper": paper, "analysis": analysis_text})
                    success_count += 1

                    if i < len(new_papers):
                        time.sleep(3) # API Rate limit 방어
                else:
                    logger.info("   -> ⚠️ Dry-Run: 플랫폼 업로드 생략 (하지만 중복 방어는 완벽히 작동했음!)")
                    success_count += 1

            except Exception as inner_e:
                logger.error(f"⚠️ 논문(PMID: {paper.get('id', 'Unknown')}) 분석/처리 실패: {inner_e}")
                continue

        # 이메일 발송
        if not dry_run and not no_email and analysis_results:
            logger.info("📧 [4/4] 처리 완료된 신규 논문 리포트를 이메일로 발송합니다...")
            notifier.send_report(analysis_results)
        elif dry_run or no_email:
            logger.info("⏩ [4/4] 이메일 발송 생략 (Dry-Run 또는 No-Email 옵션)")

        logger.info("=" * 70)
        logger.info(f"🎉 수동 실행 완벽 종료! (성공: {success_count}/{len(new_papers)}건)")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"❌ 수동 실행 메인 오류 발생: {e}", exc_info=True)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="의국 저널클럽 봇 수동 실행 스크립트")
    parser.add_argument('--days', type=int, default=7, help='최근 스캔할 일수 (기본값: 7일)')
    parser.add_argument('--dry-run', action='store_true', help='업로드 및 이메일을 생략하고 터미널에서 AI 분석 결과만 구경하기')
    parser.add_argument('--no-email', action='store_true', help='Zotero/Notion 업로드는 수행하되 단체 이메일 발송만 생략 (대규모 수집 시 유용)')
    parser.add_argument('--sync', action='store_true', help='Zotero 서버와 로컬 캐시를 강제로 재동기화')

    args = parser.parse_args()

    run_manual(days_back=args.days, dry_run=args.dry_run, no_email=args.no_email, force_sync=args.sync)
