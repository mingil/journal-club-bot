import os
import time
import logging
from google import genai
from google.genai import types

logger = logging.getLogger("JCBot")

class PaperAnalyzer:
    def __init__(self, custom_persona=None):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("❌ GEMINI_API_KEY가 없습니다.")

        self.client = genai.Client(api_key=api_key)
        self.model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash") # 최신 빠른 추론 모델 기본값 (환경변수로 변경 가능)
        self.custom_persona = custom_persona

    def _format_authors_for_prompt(self, raw_authors):
        """프롬프트 주입용 저자 및 소속 정보 포매팅 (토큰 절약 및 핵심 저자 강조)"""
        if not raw_authors:
            return "저자 소속 정보 없음"

        author_lines = []
        total_authors = len(raw_authors)

        for i, author in enumerate(raw_authors):
            name = author.get('full_name', 'Unknown')
            affil = author.get('affiliation', 'N/A')

            # 논문 신뢰도 파악의 핵심인 1저자와 교신저자 강조
            if i == 0:
                role = "[제1저자]"
            elif i == total_authors - 1 and total_authors > 1:
                role = "[교신저자(추정)]"
            else:
                # 중간 공동저자들은 토큰 절약을 위해 3명까지만 표시하고 생략
                if i > 2 and i < total_authors - 1:
                    if i == 3:
                        author_lines.append(f"  ... (외 {total_authors - 4}명의 공동저자 생략)")
                    continue
                role = f"[공동저자]"

            author_lines.append(f"- {role} {name}: {affil}")

        return "\n".join(author_lines)

    def analyze(self, paper, max_retries=3):
        # 1. 저자 소속 정보 추출
        authors_info = self._format_authors_for_prompt(paper.get('raw_authors', []))

        # 2. 페르소나를 System Instruction으로 분리 (최신 Gemini 권장 사항 - 몰입도 극대화)
        default_instruction = (
            "당신은 Evidence-Based Medicine(EBM)에 정통한 대한민국 최고 수준의 재활의학과(PM&R) 시니어 전문의이자 의과대학 교수입니다. "
            "당신의 임무는 후배 전공의들의 저널 클럽 발표를 위해, 최신 논문을 '매우 비판적이고 날카로운 시각'으로 분석하는 것입니다. "
            "저자의 주장을 무비판적으로 맹신하지 말고, 연구 디자인의 한계(N수 부족, 맹검 실패, 선택 편향 등)와 "
            "실제 임상 진료실 및 치료실 적용 가능성을 엄격하게 평가하세요."
        )
        system_instruction = self.custom_persona if self.custom_persona else default_instruction

        # 3. 프롬프트 본문 조립 (저자 전문성 평가 섹션 추가)
        prompt = f"""
아래 논문 메타데이터와 초록을 분석하여 정해진 출력 양식에 맞춰 브리핑을 작성해 주십시오.

[논문 정보]
- Title: {paper.get('title', 'N/A')}
- Journal: {paper.get('journal', 'N/A')}
- Authors & Affiliations (핵심 저자 소속):
{authors_info}

[Abstract]
{paper.get('abstract', 'N/A')}

[출력 양식 (마크다운 특수기호 최소화, 가독성 좋은 순수 텍스트 기반)]

🎯 시니어의 한 줄 평 (Takeaway):
(논문의 핵심 결과와 임상적 가치를 한 문장으로 강력하게 요약)

🧑‍⚕️ 저자 전문성 및 연구 배경 분석 (Author Credibility):
(제공된 핵심 저자들(제1저자 및 교신저자)의 소속(Affiliation)을 분석하여, 이 연구가 실제 '재활의학과 전문의(MD)' 주도로 이루어진 진료 현장의 연구인지, 아니면 공학자/기초의학자/타 보건직군(물리치료, 스포츠과학 등) 주도의 연구인지 팩트 체크하세요. 주도 연구자의 백그라운드가 연구의 임상적 신뢰도와 실제 병원 세팅(진료실/치료실) 적용에 어떤 한계를 가져올 수 있는지 날카롭게 지적하세요.)

📊 PICO 팩트 체크:
- P (대상): (환자군 및 주요 선정 기준)
- I (중재): (실험군에 적용된 핵심 치료)
- C (비교): (대조군 중재 또는 위약)
- O (결과): (1차 평가지표 및 p-value 등 주요 데이터)

🧐 비판적 평가 (Critical Appraisal):
- 칭찬할 점: (연구 디자인의 장점, 맹검 유지, 샘플 사이즈, 독창성 등)
- 치명적 한계: (저자가 숨기고 싶어 하는 약점, 통계적 오류/과장 가능성, 교란변수 통제 실패, 짧은 F/U 등 팩트 폭격)

🏥 실제 임상 적용 (Clinical Implication):
(단순 통계적 유의성(p-value)을 넘어, 당장 우리 병원 재활 진료실/치료실 루틴에 적용할 만한 최소임상적중요차이(MCID)가 있는지, 수가 청구나 현실적인 제약(시간, 비용, 장비)은 없는지 단호하게 평가)
"""

        # 4. 의학 논문용 Safety Settings 완화 (통증, 손상, 주사 등 단어로 인한 차단 방지)
        safety_settings = [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
        ]

        # 5. API 지연/오류 시 지수 백오프(Exponential Backoff) 적용
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2, # 환각 방지 및 팩트 기반 냉철한 분석 유도 (0.3 -> 0.2)
                        safety_settings=safety_settings
                    )
                )

                # Safety 정책 등으로 인해 응답 객체는 있으나 text가 없는 경우 예외 처리
                if not response.text:
                    raise ValueError("Gemini API에서 빈 텍스트를 반환했습니다. (Safety Block 차단 의심)")

                return response.text.strip()

            except Exception as e:
                logger.warning(f"⚠️ Gemini API 호출 실패 (시도 {attempt+1}/{max_retries}) [PMID: {paper.get('id', 'Unknown')}]: {e}")
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) * 4 # 4초, 8초 지수 백오프 대기
                    logger.info(f"⏳ {sleep_time}초 대기 후 재시도합니다...")
                    time.sleep(sleep_time)
                else:
                    logger.error(f"❌ Gemini API 최종 실패 (PMID: {paper.get('id', 'Unknown')})")
                    raise RuntimeError(f"Gemini API 최종 분석 실패 (PMID: {paper.get('id', 'Unknown')}): {e}")
