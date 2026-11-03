import os
import re
import time
import json
import logging
from pyzotero import zotero

logger = logging.getLogger("JCBot")

class ZoteroManager:
    def __init__(self):
        self.user_id = os.environ.get("ZOTERO_USER_ID")
        self.api_key = os.environ.get("ZOTERO_API_KEY")
        self.library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")

        # 봇이 쳐다볼 단 두 개의 '절대 좌표 (고유 ID)'
        self.candidates_col_id = os.environ.get("ZOTERO_CANDIDATES_ID")
        self.presented_col_id = os.environ.get("ZOTERO_PRESENTED_ID")

        # 🚀 [최적화 1] 로컬 캐시 파일 경로 설정 (도커 마운트 폴더 config/ 에 영구 저장)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cache_file = os.path.join(project_root, "config", "zotero_cache.json")
        self.cached_ids = set()

        if not all([self.user_id, self.api_key, self.candidates_col_id, self.presented_col_id]):
            logger.warning("⚠️ Zotero 환경변수(.env)가 누락되었습니다. Zotero 연동은 비활성화됩니다.")
            self.zot = None
            return

        try:
            self.zot = zotero.Zotero(self.user_id, self.library_type, self.api_key)
        except Exception as e:
            logger.error(f"❌ Zotero 초기화 실패: {e}")
            self.zot = None

    def _execute_with_retry(self, func, *args, max_retries=3, **kwargs):
        """API Rate limit 및 일시적 네트워크 오류 방어를 위한 백오프 래퍼"""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"⚠️ Zotero API 일시 오류 (시도 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep((2 ** attempt) * 2) # 2초, 4초, 8초 대기 후 재시도
                else:
                    logger.error("❌ Zotero API 최종 실패")
                    return None

    def _clean_doi(self, doi):
        """DOI 문자열 정규화 (URL 찌꺼기 제거 및 소문자 통일)로 중복 탐지율 극대화"""
        if not doi: return ""
        doi = str(doi).strip().lower()
        doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi)
        return doi

    def _load_cache(self):
        """로컬 json 파일에서 캐시를 읽어옵니다."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cached_ids = set(json.load(f))
                return True
            except Exception as e:
                logger.warning(f"⚠️ Zotero 로컬 캐시 읽기 실패: {e}")
        return False

    def _save_cache(self):
        """현재 캐시 셋을 json 파일로 저장합니다."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.cached_ids), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"⚠️ Zotero 로컬 캐시 저장 실패: {e}")

    def get_existing_identifiers(self, force_refresh=False):
        """🚀 [최적화 2] 로컬 캐시 우선 읽기 (0.01초 만에 완료). 최초 1회 또는 정기 백업 시 API 동기화"""
        if not self.zot: return set()

        has_cache = self._load_cache() and len(self.cached_ids) > 0

        # 1. 강제 갱신이 아니고 캐시가 있으면 Zotero API 호출 없이 초고속 리턴
        if not force_refresh and has_cache:
            logger.info(f"⚡ Zotero 로컬 캐시 적용 완료 (총 {len(self.cached_ids)}건 식별됨, 0초 소요)")
            return self.cached_ids

        # 2. 캐시가 비어있거나 정기 백업(force_refresh=True)인 경우 Zotero 서버와 동기화
        try:
            if force_refresh and has_cache:
                logger.info("🔄 Zotero 서버와 로컬 캐시 정기 동기화를 수행합니다...")
            else:
                logger.info("🐌 Zotero 로컬 캐시가 없습니다. 최초 1회 전체 데이터를 스캔하여 캐시를 생성합니다... (다소 시간 소요)")
            existing_ids = set(self.cached_ids)

            def fetch_all(col_id):
                first_page = self.zot.collection_items(col_id)
                if not first_page: return []
                return self.zot.everything(first_page)

            candidates_items = self._execute_with_retry(fetch_all, self.candidates_col_id) or []
            presented_items = self._execute_with_retry(fetch_all, self.presented_col_id) or []

            all_items = candidates_items + presented_items

            for item in all_items:
                data = item.get('data', {})

                doi = self._clean_doi(data.get('DOI', ''))
                if doi:
                    existing_ids.add(doi)

                if 'extra' in data and data['extra']:
                    for line in data['extra'].split('\n'):
                        if line.upper().startswith('PMID:'):
                            pmid = re.sub(r'\D', '', line.replace('PMID:', '').replace('pmid:', ''))
                            if pmid: existing_ids.add(pmid)

            logger.info(f"✅ Zotero DB 동기화 완료: 기존 논문 총 {len(existing_ids)}건 식별됨")

            # 3. 긁어온 결과를 메모리에 담고 로컬 캐시에 영구 저장!
            self.cached_ids = existing_ids
            self._save_cache()

            return self.cached_ids

        except Exception as e:
            logger.error(f"⚠️ Zotero 지정 폴더 데이터 로드 실패: {e}")
            return self.cached_ids if has_cache else set()

    def add_paper_to_candidates(self, paper, analysis_text=""):
        """어떠한 불순물(태그, 노트, 이모지)도 없이 '순정 메타데이터'만 Zotero에 업로드합니다."""
        if not self.zot: return False

        try:
            template = self._execute_with_retry(self.zot.item_template, 'journalArticle')
            if not template: return False

            # [순정 데이터 1:1 매핑 구역]
            template['title'] = str(paper.get('title', 'Unknown Title')).strip()
            template['DOI'] = self._clean_doi(paper.get('doi', ''))
            template['abstractNote'] = str(paper.get('abstract', '')).strip()
            template['publicationTitle'] = str(paper.get('journal', '')).strip()
            template['date'] = str(paper.get('date', '')).strip()
            template['url'] = str(paper.get('link', '')).strip()

            pmid = str(paper.get('id', '')).strip()
            template['extra'] = f"PMID: {pmid}"

            # --- 저자 정보 파싱 ---
            creators = []
            for author in paper.get('raw_authors', []):
                first_name = str(author.get('first', '')).strip()
                last_name = str(author.get('last', '')).strip()
                full_name = str(author.get('full_name', '')).strip()

                if first_name or last_name:
                    creators.append({'creatorType': 'author', 'firstName': first_name, 'lastName': last_name})
                elif full_name:
                    creators.append({'creatorType': 'author', 'name': full_name})

            # API 거부 에러(400) 방지를 위한 기본값 주입
            if not creators:
                creators.append({'creatorType': 'author', 'lastName': 'Unknown Author'})

            template['creators'] = creators
            template['collections'] = [self.candidates_col_id]

            # 1. 꼬리표(태그/자식노트) 없이 깔끔하게 메인 논문만 단일 호출로 업로드!
            resp = self._execute_with_retry(self.zot.create_items, [template])

            if resp and resp.get('successful'):
                logger.info(f"💾 Zotero 순정 업로드 완료: {template['title'][:30]}...")

                # 🚀 [최적화 3] Zotero 서버에 성공적으로 올라갔다면, 로컬 캐시에도 새 논문 실시간 추가!
                updated = False
                if template['DOI']:
                    self.cached_ids.add(template['DOI'])
                    updated = True
                if pmid:
                    self.cached_ids.add(pmid)
                    updated = True

                if updated:
                    self._save_cache()

                return True
            else:
                logger.error(f"⚠️ Zotero 업로드 실패: {resp.get('failed') if resp else 'No Response'}")
                return False

        except Exception as e:
            logger.error(f"⚠️ Zotero API 로직 에러: {e}")
            return False
