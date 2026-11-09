import os
import re
import html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
import logging

logger = logging.getLogger("JCBot")

class EmailNotifier:
    def __init__(self):
        self.email = os.environ.get("EMAIL")
        self.password = os.environ.get("EMAIL_PASSWORD")
        self.smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "465"))

        # 🚀 [최적화 1] 다중 수신자 지원 (환경변수 EMAIL_TO를 콤마로 구분하여 여러 명에게 발송 가능)
        raw_recipients = os.environ.get("EMAIL_TO", self.email)
        if raw_recipients:
            self.recipients = [email.strip() for email in str(raw_recipients).split(',') if email.strip()]
        else:
            self.recipients = []

    def _parse_markdown(self, text):
        """🚀 [최적화 2] AI의 마크다운 텍스트를 이메일 클라이언트에 최적화된 예쁜 HTML로 변환"""
        if not text:
            return "<p>분석 결과가 없습니다.</p>"

        # 0. 의학 논문 내 부등호(예: p < 0.05)가 HTML 태그로 오인되어 잘리는 현상 방지
        text = html.escape(text)

        # 1. 볼드체 변환 (**텍스트** -> <b>텍스트</b>) (태그 안 닫힘 버그 원천 차단)
        text = re.sub(r'\*\*(.*?)\*\*', r'<b style="color: #111827;">\1</b>', text)

        # 2. 줄 단위 파싱 (헤더, 리스트, 일반 텍스트 분리 및 모던 스타일링)
        lines = text.split('\n')
        html_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                html_lines.append('<div style="height: 12px;"></div>')
                continue

            # analyzer.py 의 출력 양식(이모지)과 연동하여 예쁜 박스 UI 자동 생성
            if line.startswith('🎯'): # 한 줄 평 (노란색)
                html_lines.append(f'<div style="background-color: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 20px 0 10px 0; font-weight: bold; color: #92400e; border-radius: 4px;">{line}</div>')
            elif line.startswith('🧑‍⚕️'): # 저자 전문성 (회색)
                html_lines.append(f'<div style="background-color: #f3f4f6; border-left: 4px solid #6b7280; padding: 12px 16px; margin: 20px 0 10px 0; font-weight: bold; color: #374151; border-radius: 4px;">{line}</div>')
            elif line.startswith('📊'): # PICO (파란색 밑줄 헤더)
                html_lines.append(f'<div style="margin: 20px 0 10px 0; font-weight: bold; color: #1d4ed8; border-bottom: 2px solid #bfdbfe; padding-bottom: 4px; font-size: 1.1em;">{line}</div>')
            elif line.startswith('🧐'): # 비판적 평가 (빨간색)
                html_lines.append(f'<div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; margin: 20px 0 10px 0; font-weight: bold; color: #991b1b; border-radius: 4px;">{line}</div>')
            elif line.startswith('🏥'): # 실제 임상 적용 (초록색)
                html_lines.append(f'<div style="background-color: #ecfdf5; border-left: 4px solid #10b981; padding: 12px 16px; margin: 20px 0 10px 0; font-weight: bold; color: #065f46; border-radius: 4px;">{line}</div>')
            elif line.startswith('- '): # 리스트 불릿
                html_lines.append(f'<div style="margin-left: 16px; margin-bottom: 6px; line-height: 1.6; color: #4b5563;">• {line[2:]}</div>')
            else: # 일반 텍스트
                html_lines.append(f'<div style="margin-bottom: 6px; line-height: 1.6; color: #374151;">{line}</div>')

        return "".join(html_lines)

    def send_report(self, results):
        if not self.email or not self.password:
            logger.error("❌ 이메일 설정(EMAIL, EMAIL_PASSWORD)이 누락되어 리포트를 발송할 수 없습니다.")
            return

        if not self.recipients:
            logger.error("❌ 수신자 이메일 목록이 비어있습니다.")
            return

        if not results:
            logger.info("ℹ️ 발송할 논문 결과가 없습니다.")
            return

        subject = f"[의국 저널클럽] 이번 주 재활의학과 추천 논문 리포트 ({len(results)}건)"

        # 🚀 [최적화 3] 반응형 이메일 상단 헤더 및 목차(TOC) 생성
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; line-height: 1.6; color: #1f2937; max-width: 800px; margin: 0 auto; background-color: #f3f4f6; padding: 20px;">
            <div style="background-color: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-top: 6px solid #2563eb;">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h2 style="color: #1e40af; margin: 0; font-size: 26px;">🏥 의국 저널클럽 추천 논문</h2>
                    <p style="color: #6b7280; margin-top: 10px; font-size: 15px;">이번 주 선정된 <b>{len(results)}건</b>의 최신 RCT 및 시니어 교수의 비판적 분석</p>
                </div>

                <div style="background-color: #f8fafc; padding: 20px; border-radius: 8px; margin-bottom: 40px; border: 1px solid #e2e8f0;">
                    <h4 style="margin-top: 0; color: #334155; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px;">📑 오늘의 논문 브리핑 목차</h4>
                    <ul style="margin-bottom: 0; padding-left: 20px; color: #2563eb;">
        """

        for idx, res in enumerate(results, 1):
            title = html.escape(str(res.get('paper', {}).get('title', '제목 없음')))
            html_body += f'<li style="margin-bottom: 8px;"><a href="#paper-{idx}" style="color: #2563eb; text-decoration: none;">{title}</a></li>'

        html_body += """
                    </ul>
                </div>
        """

        # --- 개별 논문 분석 파트 ---
        for idx, res in enumerate(results, 1):
            p = res.get('paper', {})
            a = res.get('analysis', "분석 결과가 없습니다.")

            a_html = self._parse_markdown(a)

            # MD 확실성 뱃지 동적 생성 ('High' in 조건으로 버그 수정)
            md_cert = html.escape(str(p.get('md_certainty', 'Unknown')))
            if 'High' in md_cert:
                badge_bg, badge_color = "#dcfce7", "#166534" # 초록색
            else:
                badge_bg, badge_color = "#fef3c7", "#92400e" # 노란색

            certainty_badge = f'<span style="background-color: {badge_bg}; color: {badge_color}; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-left: 10px; display: inline-block;">🧑‍⚕️ {md_cert}</span>'

            safe_title = html.escape(str(p.get('title', '제목 없음')))
            safe_journal = html.escape(str(p.get('journal', 'N/A')))
            safe_date = html.escape(str(p.get('date', 'N/A')))
            safe_authors = html.escape(str(p.get('authors', 'N/A')))
            safe_link = html.escape(str(p.get('link', '#')))

            html_body += f"""
                <div id="paper-{idx}" style="margin-bottom: 50px; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;">

                    <div style="background-color: #f8fafc; padding: 20px 25px; border-bottom: 1px solid #e5e7eb;">
                        <div style="font-size: 13px; color: #64748b; font-weight: bold; margin-bottom: 10px; display: flex; align-items: center;">
                            <span style="background-color: #2563eb; color: white; padding: 2px 8px; border-radius: 4px; margin-right: 10px;">#{idx}</span>
                            논문 리뷰
                        </div>
                        <h3 style="margin: 0 0 15px 0; font-size: 19px; line-height: 1.5;">
                            <a href="{safe_link}" target="_blank" style="color: #111827; text-decoration: none;">{safe_title}</a>
                        </h3>
                        <div style="font-size: 14px; color: #475569; background-color: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                            <p style="margin: 0 0 8px 0;">📚 <b>저널:</b> {safe_journal} &nbsp;|&nbsp; <b>출판일:</b> {safe_date} {certainty_badge}</p>
                            <p style="margin: 0;">✍️ <b>저자:</b> {safe_authors}</p>
                        </div>
                    </div>

                    <div style="padding: 25px; background-color: #ffffff;">
                        <h4 style="color: #2563eb; border-bottom: 2px solid #bfdbfe; padding-bottom: 8px; margin-top: 0; margin-bottom: 20px; font-size: 16px;">🤖 AI 시니어 교수의 브리핑</h4>
                        <div style="font-size: 15px; color: #374151; line-height: 1.7;">
                            {a_html}
                        </div>
                    </div>

                    <div style="background-color: #f8fafc; padding: 15px 25px; border-top: 1px solid #e5e7eb; text-align: right;">
                        <a href="{safe_link}" target="_blank" style="display: inline-block; background-color: #2563eb; color: white; text-decoration: none; padding: 10px 20px; border-radius: 6px; font-size: 14px; font-weight: bold; transition: background-color 0.2s;">PubMed 원문 열기 ↗</a>
                    </div>
                </div>
            """

        # --- 푸터 ---
        html_body += """
                <div style="text-align: center; margin-top: 40px; padding-top: 20px; color: #9ca3af; font-size: 13px; border-top: 1px solid #e5e7eb;">
                    <p style="margin: 0;">Generated by <b>Rehab Journal Club Bot</b> (Powered by Google Gemini)</p>
                    <p style="margin: 5px 0;">본 이메일은 자동 발송되었습니다. 논문 전문(PDF)은 Zotero 공유 폴더를 확인하세요.</p>
                </div>
            </div>
        </body>
        </html>
        """

        # --- 🚀 [최적화 4] 메일 발송 (UTF-8 인코딩 및 Timeout 적용, SSL/STARTTLS 자동 호환) ---
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = f"의국 JC Bot <{self.email}>"
            msg['To'] = ", ".join(self.recipients)
            msg['Subject'] = subject
            msg['Date'] = formatdate(localtime=True)
            msg['Message-ID'] = make_msgid()

            # 명시적 UTF-8 인코딩으로 한글 깨짐 원천 방지
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            # SMTP 타임아웃 15초 적용 (무한 로딩 방지)
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=15) as server:
                    server.login(self.email, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=15) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(self.email, self.password)
                    server.send_message(msg)

            logger.info(f"📧 이메일 리포트 발송 완료! (수신자: {len(self.recipients)}명)")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("❌ 이메일 인증 실패: 앱 비밀번호(App Password)를 확인하세요.")
            return False
        except Exception as e:
            logger.error(f"❌ 이메일 발송 중 알 수 없는 오류 발생: {e}")
            return False

class TelegramNotifier:
    """신규 논문 요약·치명적 오류를 텔레그램으로 알림 (선택 기능).
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 가 모두 있을 때만 동작하고, 없으면 조용히 건너뛴다."""

    API = "https://api.telegram.org/bot{token}/sendMessage"
    LIMIT = 3900  # 텔레그램 메시지 최대 4096자 — 여유를 두고 나눔

    def __init__(self):
        self.token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip().strip('"').strip("'")
        self.chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip().strip('"').strip("'")
        self.enabled = bool(self.token and self.chat_id)

    def _send(self, text):
        if not self.enabled:
            return False
        import requests
        try:
            r = requests.post(self.API.format(token=self.token),
                              data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}, timeout=20)
            if r.status_code != 200:
                logger.error(f"❌ 텔레그램 발송 실패: HTTP {r.status_code}")
                return False
            return True
        except Exception as e:
            logger.error(f"❌ 텔레그램 발송 오류: {type(e).__name__}")
            return False

    @staticmethod
    def _one_liner(analysis):
        for line in (analysis or "").splitlines():
            if line.strip().startswith("🎯"):
                return re.sub(r"\*\*", "", line.strip())[:300]
        return ""

    def send_report(self, results):
        if not self.enabled or not results:
            return
        e = html.escape
        blocks = [f"🏥 <b>의국 저널클럽 신규 논문 {len(results)}건</b>\n(자세한 분석은 메일·Notion 참고)"]
        for i, item in enumerate(results, 1):
            p = item.get("paper", {})
            meta = " · ".join(x for x in (p.get("journal"), p.get("date")) if x)
            b = f"\n<b>{i}. {e(str(p.get('title', ''))[:250])}</b>"
            if meta:
                b += f"\n📚 {e(meta)}"
            one = self._one_liner(item.get("analysis"))
            if one:
                b += f"\n{e(one)}"
            if p.get("link"):
                b += f"\n🔗 {e(p['link'])}"
            blocks.append(b)
        msg, sent = "", 0
        for b in blocks:
            if len(msg) + len(b) > self.LIMIT and msg:
                sent += self._send(msg); msg = ""
            msg += b + "\n"
        if msg:
            sent += self._send(msg)
        if sent:
            logger.info(f"📨 텔레그램 요약 발송 완료 ({len(results)}건)")

    def send_error(self, mode_name, err):
        self._send(f"⚠️ <b>저널클럽 봇 오류</b> [{html.escape(str(mode_name))}]\n{html.escape(str(err))[:500]}")
