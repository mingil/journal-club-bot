import os
import re
import time
import datetime
import logging
import http.client
from urllib.error import HTTPError, URLError
import jcr_lookup
from Bio import Entrez

logger = logging.getLogger("JCBot")

class MDFetcher:
    def __init__(self, email, filter_config=None):
        Entrez.email = email
        self.filter_config = filter_config or {}
        self.strict_md_filter = self.filter_config.get("strict_md_filter", True)

        # 🛡️ NCBI API Key 적용 및 Rate Limit 딜레이 자동 설정
        ncbi_api_key = os.environ.get("NCBI_API_KEY")
        if ncbi_api_key:
            Entrez.api_key = ncbi_api_key
            self.sleep_time = 0.11  # API Key 있음: 초당 10회 요청 제한 방어
        else:
            self.sleep_time = 0.35  # API Key 없음: 초당 3회 요청 제한 방어

        # 🚀 [최적화 1] 정규식 사전 컴파일 - 단어 경계(\b) 매칭으로 오탐(polymer 등) 차단
        # 타 진료과/연구실에서도 settings.yaml의 specialty_keywords로 손쉽게 커스터마이징 가능 (기본값: 재활의학과)
        custom_keywords = self.filter_config.get("specialty_keywords")
        if custom_keywords and isinstance(custom_keywords, list):
            kw_joined = "|".join([re.escape(str(k).strip()) for k in custom_keywords if str(k).strip()])
            self.rehab_pattern = re.compile(rf'\b({kw_joined})\b', re.IGNORECASE)
        else:
            self.rehab_pattern = re.compile(
                r'\b(rehabilitation|physical medicine|physiatry|physiatrist|pm&r|pmr)\b',
                re.IGNORECASE
            )
        self.medical_pattern = re.compile(
            r'\b(hospital|clinic|medical center|school of medicine|college of medicine|faculty of medicine|medical school|clinical)\b',
            re.IGNORECASE
        )
        # 🚀 [최적화 2] 네거티브 필터링 - 기초/타 보건직군 노이즈 차단
        self.exclude_pattern = re.compile(
            r'\b(physical therapy|occupational therapy|nursing|engineering|kinesiology|sports science|biomechanics)\b',
            re.IGNORECASE
        )
        # 의사 면허(MD) 명시 패턴
        self.md_pattern = re.compile(r'\b(m\.?d\.?|medical doctor|physician|d\.?o\.?|mbbs)\b', re.IGNORECASE)

    def _is_strict_pmr(self, authors_list):
        """1저자와 교신저자가 확실한 '전문의/임상의/교수(MD)'인지 검사하는 최적화 로직"""
        if not self.strict_md_filter:
            return True
        if not authors_list:
            return False

        def is_md_physiatrist(author):
            if not author:
                return False

            text = f"{author.get('suffix', '')} {author.get('affiliation', '')}".lower()
            if not text.strip():
                return False

            # [1단계: 재활 필수 키워드]
            if not self.rehab_pattern.search(text):
                return False

            # [2단계: 임상/의대 화이트리스트 검사]
            if not self.medical_pattern.search(text) and not self.md_pattern.search(text):
                return False

            # [3단계: 네거티브 필터링] 타 직군/기초과학 단독 소속 배제
            if self.exclude_pattern.search(text):
                # 단, 명시적으로 MD/DO 등의 타이틀이 있다면 구제 (이중 소속 의사 등)
                if not self.md_pattern.search(text):
                    return False

            return True

        # 1저자(authors_list[0]) 또는 교신저자(authors_list[-1]) 중 한 명이라도 만족하면 True
        return is_md_physiatrist(authors_list[0]) or is_md_physiatrist(authors_list[-1])

    def _fetch_with_retry(self, func, *args, max_retries=3, **kwargs):
        """🚀 [최적화 3] NCBI API 서버 장애 완벽 방어용 지수 백오프(Exponential Backoff) 및 DTD 우회 로직"""
        for attempt in range(max_retries):
            try:
                time.sleep(self.sleep_time) # IP 블락 방지용 Rate limit 딜레이
                handle = func(*args, **kwargs)

                # 🔥 [핵심 최적화: validate=False 추가]
                # NCBI 서버에서 DTD 문법 파일을 불러오려다 타임아웃 나는 에러를 원천 차단합니다!
                result = Entrez.read(handle, validate=False)

                handle.close()
                return result
            except (HTTPError, URLError, http.client.IncompleteRead) as e:
                wait_time = 2 ** attempt
                logger.warning(f"⚠️ NCBI API 네트워크 오류 ({e}). {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                # 🔥 [안전망 강화] DTD 에러나 알 수 없는 파싱 에러 발생 시 바로 포기(break)하지 않고 백오프 후 끈질기게 재시도!
                wait_time = 2 ** attempt
                logger.warning(f"⚠️ Entrez 파싱/알 수 없는 오류 ({e}). {wait_time}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)

        logger.error(f"❌ NCBI API 최종 실패 ({max_retries}회 시도 초과)")
        return None

    def _parse_article(self, article):
        """🚀 [최적화 6] 단일 논문 파싱 모듈화 (들여쓰기 Depth 감소 및 에러 격리)"""
        try:
            medline = article.get('MedlineCitation', {})
            article_data = medline.get('Article', {})
            pmid = str(medline.get('PMID', ''))

            # str() 명시적 캐스팅으로 Biopython StringElement JSON 직렬화 에러 원천 차단
            title = str(article_data.get('ArticleTitle', 'No Title'))

            # --- 1. 저자 파싱 ---
            raw_authors = []
            if 'AuthorList' in article_data:
                for author in article_data['AuthorList']:
                    last = str(author.get('LastName', ''))
                    first = str(author.get('ForeName', author.get('Initials', '')))
                    suffix = str(author.get('Suffix', ''))

                    # 빈 문자열(None) 필터링 최적화
                    affils_list = [str(info.get('Affiliation', '')) for info in author.get('AffiliationInfo', [])]
                    affil = " | ".join(filter(None, affils_list)) if affils_list else "N/A"

                    raw_authors.append({
                        'last': last, 'first': first, 'suffix': suffix, 'affiliation': affil,
                        'full_name': f"{last} {first} {suffix}".strip()
                    })

            # 🛑 엄격해진 화이트리스트/네거티브 결합 MD 검사
            if not self._is_strict_pmr(raw_authors):
                return None

            authors_str = ", ".join([a['full_name'] for a in raw_authors[:3]])
            if len(raw_authors) > 3:
                authors_str += " et al."

            # --- 2. DOI 이중 확인 파싱 (결측치 방지) ---
            doi = ""
            if 'ELocationID' in article_data:
                for eloc in article_data['ELocationID']:
                    if getattr(eloc, 'attributes', {}).get('EIdType') == 'doi':
                        doi = str(eloc)
                        break
            if not doi and 'PubmedData' in article and 'ArticleIdList' in article['PubmedData']:
                for art_id in article['PubmedData']['ArticleIdList']:
                    if getattr(art_id, 'attributes', {}).get('IdType') == 'doi':
                        doi = str(art_id)
                        break

            # --- 3. 🚀 [최적화 5] 초록(Abstract) 마크다운 구조화 (가독성 향상) ---
            abstract_text = "No Abstract Available."
            if 'Abstract' in article_data and 'AbstractText' in article_data['Abstract']:
                abs_elements = article_data['Abstract']['AbstractText']
                if isinstance(abs_elements, list):
                    abs_parts = []
                    for elem in abs_elements:
                        label = getattr(elem, 'attributes', {}).get('Label', '')
                        text = str(elem).strip()
                        if label and label.lower() != 'unlabelled': # BACKGROUND, METHODS 등
                            abs_parts.append(f"**{label.upper()}**: {text}")
                        else:
                            abs_parts.append(text)
                    abstract_text = "\n\n".join(abs_parts)
                else:
                    abstract_text = str(abs_elements)

            # --- 4. 출판일 및 저널 파싱 ---
            journal = str(article_data.get('Journal', {}).get('Title', 'Unknown Journal'))
            issn = str(article_data.get('Journal', {}).get('ISSN', '') or '').strip()
            pub_date = article_data.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {})

            try:
                if 'Year' in pub_date and 'Month' in pub_date:
                    date_str = f"{pub_date['Year']} {pub_date['Month']}".strip()
                elif 'Year' in pub_date:
                    date_str = str(pub_date['Year'])
                elif 'MedlineDate' in pub_date:
                    date_str = str(pub_date['MedlineDate'])
                else:
                    date_str = "Unknown Date"
            except Exception:
                date_str = "Unknown Date"

            return {
                'id': pmid, 'doi': doi, 'title': title, 'abstract': abstract_text,
                'journal': journal, 'date': date_str, 'authors': authors_str,
                'issn': issn, 'jcr': jcr_lookup.lookup(issn, journal),
                'raw_authors': raw_authors,
                'md_certainty': 'High (PM&R MD Only)',
                'link': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            }
        except Exception as inner_e:
            logger.warning(f"⚠️ 개별 논문 파싱 중 오류 발생 (PMID: {pmid if 'pmid' in locals() else 'Unknown'}): {inner_e}")
            return None

    def fetch_recent_papers(self, journals, days_back):
        today = datetime.datetime.now()
        start_date = today - datetime.timedelta(days=days_back)

        date_query = f'(("{start_date.strftime("%Y/%m/%d")}"[Date - Create] : "{today.strftime("%Y/%m/%d")}"[Date - Create]))'
        journal_terms = " OR ".join([f'"{j}"[Journal]' for j in journals])

        rct_list = [
            '"Randomized Controlled Trial"[pt]',
            '"randomized controlled trial"[tiab]',
            '"randomised controlled trial"[tiab]',
            '"randomized clinical trial"[tiab]',
            '"randomised clinical trial"[tiab]'
        ]
        pt_terms = " OR ".join(rct_list)
        full_query = f'({journal_terms}) AND {date_query} AND ({pt_terms})'

        logger.info(f"🔍 PubMed 검색 시작 (기간: {days_back}일, MD 정밀필터 적용)")

        try:
            # 안전한 eSearch 호출
            search_results = self._fetch_with_retry(
                Entrez.esearch, db="pubmed", term=full_query, retmax=10000, sort="pub_date"
            )

            if not search_results:
                return []

            id_list = search_results.get("IdList", [])

            if not id_list:
                logger.info("ℹ️ 해당 기간 조건에 맞는 논문이 없습니다.")
                return []

            logger.info(f"📄 예비 논문 총 {len(id_list)}건 발견. 병목 방지 배치(Batch) 추출 및 필터링 시작...")

            papers = []
            batch_size = 100

            for start in range(0, len(id_list), batch_size):
                batch_ids = id_list[start:start+batch_size]

                # 안전한 eFetch 호출
                articles = self._fetch_with_retry(
                    Entrez.efetch, db="pubmed", id=",".join(batch_ids), rettype="xml", retmode="xml"
                )

                if not articles or 'PubmedArticle' not in articles:
                    continue

                for article in articles['PubmedArticle']:
                    parsed_paper = self._parse_article(article)
                    if parsed_paper: # None이 아니면 (MD 검사 통과 및 파싱 성공)
                        papers.append(parsed_paper)

            logger.info(f"✅ 최종 필터링 완료: 재활의학과 전문의(MD) 주도 RCT 논문 - 총 {len(papers)}건")
            return papers

        except Exception as e:
            logger.error(f"❌ PubMed 전체 검색 프로세스 에러: {e}")
            return []
