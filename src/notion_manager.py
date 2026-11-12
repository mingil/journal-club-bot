import os
import re
import time
import logging
from notion_client import Client
import jcr_lookup

logger = logging.getLogger("JCBot")

class NotionManager:
    def __init__(self):
        token = os.environ.get("NOTION_API_KEY")
        self.database_id = os.environ.get("NOTION_DATABASE_ID")

        if not token or not self.database_id:
            logger.warning("⚠️ Notion API 키 또는 Database ID가 없습니다. 노션 업로드는 건너뜁니다.")
            self.notion = None
        else:
            self.notion = Client(auth=token)

    def _parse_rich_text(self, text):
        """🚀 [최적화 1] 마크다운 **볼드체**를 노션 Rich Text 객체로 완벽 변환 (2000자 제한 방어)"""
        if not text:
            return []

        # **기호**를 기준으로 텍스트 분할
        parts = re.split(r'(\*\*.*?\*\*)', text)
        rich_text_list = []

        for part in parts:
            if not part:
                continue

            is_bold = False
            if part.startswith('**') and part.endswith('**') and len(part) >= 4:
                is_bold = True
                part = part[2:-2] # 양끝 ** 기호 제거

            # 🛡️ 2000자 제한 방어를 위한 청킹(Chunking)
            for i in range(0, len(part), 1900):
                chunk = part[i:i+1900]
                rich_text_list.append({
                    "type": "text",
                    "text": {"content": chunk},
                    "annotations": {"bold": is_bold}
                })

        return rich_text_list

    def _build_blocks(self, paper, analysis_text):
        """🚀 [최적화 2] 예쁜 UI/UX를 위한 노션 블록(Block) 디자인 조립"""
        blocks = [
            {
                "object": "block", "type": "callout",
                "callout": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "📚 논문 메타데이터\n"}, "annotations": {"bold": True}},
                        {"type": "text", "text": {"content": f"• 저널: {paper.get('journal', 'N/A')} (발행일: {paper.get('date', 'N/A')})\n"}},
                        *([{"type": "text", "text": {"content": f"• JCR: {jcr_lookup.label(paper)}\n"}}] if jcr_lookup.label(paper) else []),
                        {"type": "text", "text": {"content": f"• 저자: {paper.get('authors', 'N/A')}\n"}},
                        {"type": "text", "text": {"content": f"• PMID: {paper.get('id', 'N/A')} | DOI: {paper.get('doi', 'N/A')}"}}
                    ],
                    "icon": {"type": "emoji", "emoji": "🔖"},
                    "color": "gray_background"
                }
            },
            {
                "object": "block", "type": "bookmark",
                "bookmark": {"url": paper.get('link', f"https://pubmed.ncbi.nlm.nih.gov/{paper.get('id', '')}/")}
            },
            {"object": "block", "type": "divider", "divider": {}}
        ]

        # 🚀 [최적화 3] 원문 초록을 토글(Toggle) 블록에 안전하게 숨김
        abstract_text = paper.get('abstract', 'No Abstract Available.')
        abstract_blocks = []
        for i in range(0, len(abstract_text), 1900):
            abstract_blocks.append({
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": abstract_text[i:i+1900]}}]}
            })

        blocks.append({
            "object": "block", "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": "📄 영문 초록 (Abstract) 원문 보기"}, "annotations": {"bold": True, "color": "gray"}}],
                "color": "gray_background",
                "children": abstract_blocks[:100] # 토글 내부 100개 블록 한도 방어
            }
        })

        blocks.append({"object": "block", "type": "divider", "divider": {}})
        blocks.append({
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🤖 AI 시니어 교수의 브리핑"}}], "color": "blue_background"}
        })

        # 🚀 [최적화 1] AI 분석 텍스트를 감지하여 Callout 박스 등 맞춤형으로 자동 변환
        for paragraph in analysis_text.split('\n'):
            line = paragraph.strip()
            if not line:
                continue

            # 이모지 제거 후 깔끔하게 텍스트만 박스에 넣기 (배경색 지정)
            if line.startswith('🎯'):
                clean_line = line.replace('🎯', '', 1).strip()
                blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": self._parse_rich_text(clean_line), "icon": {"type": "emoji", "emoji": "🎯"}, "color": "yellow_background"}})
            elif line.startswith('🧑‍⚕️'):
                clean_line = line.replace('🧑‍⚕️', '', 1).strip()
                blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": self._parse_rich_text(clean_line), "icon": {"type": "emoji", "emoji": "🧑‍⚕️"}, "color": "gray_background"}})
            elif line.startswith('📊'):
                blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": self._parse_rich_text(line), "color": "blue_background"}})
            elif line.startswith('🧐'):
                clean_line = line.replace('🧐', '', 1).strip()
                blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": self._parse_rich_text(clean_line), "icon": {"type": "emoji", "emoji": "🧐"}, "color": "red_background"}})
            elif line.startswith('🏥'):
                clean_line = line.replace('🏥', '', 1).strip()
                blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": self._parse_rich_text(clean_line), "icon": {"type": "emoji", "emoji": "🏥"}, "color": "green_background"}})
            elif line.startswith('- ') or line.startswith('* '):
                blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": self._parse_rich_text(line[2:])}})
            else:
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._parse_rich_text(line)}})

        return blocks

    def upload_paper(self, paper, analysis_text, max_retries=3):
        if not self.notion:
            return False

        children_blocks = self._build_blocks(paper, analysis_text)

        # 🛡️ 100개 블록 제한 방어를 위한 분할 전송 준비
        first_batch = children_blocks[:100]
        remaining_blocks = children_blocks[100:]

        # 🚀 [최적화 4] 노션 DB 언어 설정에 따른 기본 속성명(Title) 자동 탐색 및 백오프 재시도
        title_candidates = ["이름", "Name", "Title", "title"]
        title_prop_name = None
        created_page = None
        last_error = None

        title_text = paper.get('title', 'No Title')[:1900]

        for attempt in range(max_retries):
            try:
                if not title_prop_name:
                    # 컬럼명을 모를 경우 순회하며 찾기 (Zero-Config)
                    for t_name in title_candidates:
                        try:
                            created_page = self.notion.pages.create(
                                parent={"database_id": self.database_id},
                                icon={"type": "emoji", "emoji": "📑"}, # 리스트에서 예쁘게 보이도록 문서 아이콘 고정
                                properties={
                                    t_name: {"title": [{"type": "text", "text": {"content": title_text}}]}
                                },
                                children=first_batch
                            )
                            title_prop_name = t_name
                            break
                        except Exception as inner_e:
                            if "property" in str(inner_e).lower() or "not find" in str(inner_e).lower():
                                last_error = inner_e
                                continue
                            else:
                                raise inner_e # 속성명 문제가 아니면 상위 catch로 던짐
                else:
                    # 컬럼명을 이미 찾은 경우 재시도
                    created_page = self.notion.pages.create(
                        parent={"database_id": self.database_id},
                        icon={"type": "emoji", "emoji": "📑"},
                        properties={
                            title_prop_name: {"title": [{"type": "text", "text": {"content": title_text}}]}
                        },
                        children=first_batch
                    )

                if created_page:
                    break # 성공 시 루프 탈출

            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ 노션 API 호출 실패 (시도 {attempt+1}/{max_retries}): {e}")
                time.sleep((2 ** attempt) * 2) # Rate limit 방어를 위한 지수 백오프 (2초, 4초 대기)

        if not created_page:
            logger.error(f"❌ 노션 업로드 최종 실패: {last_error}")
            return False

        # --- 🛡️ 100개 초과된 블록이 있다면 이어서 업로드(Append) ---
        if remaining_blocks:
            for i in range(0, len(remaining_blocks), 100):
                batch = remaining_blocks[i:i+100]
                try:
                    self.notion.blocks.children.append(
                        block_id=created_page["id"],
                        children=batch
                    )
                    time.sleep(0.5) # 연쇄 호출 시 노션 서버 과부하 방지
                except Exception as e:
                    logger.error(f"⚠️ 노션 추가 블록 업로드 실패: {e}")

        logger.info(f"📝 노션 아카이빙 완료: {title_text[:30]}...")
        return True