# crosspoint-brief

CrossPoint 펌웨어를 쓰는 Xteink X4용 개인 아침 브리핑 발행 서버.
펌웨어 포크는 별도 저장소 `G:\gg\crosspoint-reader` (P1 동기화 클라이언트 담당).
명세: Claude Docs "E-ink 개인 출판 플랫폼 v0 명세" https://claude.ai/artifact/AP4pnvSicATFkPTHGYYM1v — 결정은 이 문서가 기준이다.

## 명령

- 설치: `uv sync`
- 테스트: `uv run pytest` (네트워크 없이 통과해야 한다)
- 린트·포맷: `uv run ruff check .`, `uv run ruff format .`
- 실행: `uv run brief collect | publish [--force] [--no-collect] | serve | run [--serve PORT] | status`
- 설정: `config.toml` (예시 `config.example.toml`). P0-3에서 Synology 웹 관리 화면으로 옮긴다.

## 구조 규칙

- 흐름: `connectors/` → ContentItem(SQLite, `db.py`) → `pipeline/select.py` → `compose.py` → `render/`(epub, opds) → `pipeline/publish.py`.
- 뒤 단계는 ContentItem만 본다. 새 입력원 유형 = `connectors/`에 클래스 하나 + 레지스트리 등록 한 줄. 사이트별 전용 코드는 만들지 않는다.
- LLM 단계에는 반드시 규칙 대체가 있어야 하고, 대체된 단계는 브리프의 "발행 정보" 장에 표시한다.
- 시각은 DB에 UTC(`...Z`)로 저장하고, 표시는 `publish.timezone` 기준.

## CrossPoint 호환 (어기면 기기에서 깨진다)

- 장(XHTML)은 expat(`XML_GE=0`)으로 파싱된다: 이름 있는 엔티티 금지. 피드 HTML은 반드시 `render/sanitize.py`를 거친다.
- OPDS href는 `/`로 시작하는 절대 경로 (`UrlUtils::buildUrl`이 상대 경로를 `/`만 붙여 잇는다). 책 링크 type은 정확히 `application/epub+zip`.
- 기사 1개 = spine 1개, nav + NCX 모두, 폰트 임베드 없음. 같은 입력이면 같은 바이트(P1 SHA256 검증용).
- 펌웨어 동작을 근거로 삼을 때는 `G:\gg\crosspoint-reader` 코드를 직접 읽고 파일:줄을 남긴다.

## 운영 환경

- 배포: XPEnology(Pentium G4600, AVX 없음, RAM 16GB) Docker. AVX가 필요한 패키지·이미지는 쓰지 않는다. 로컬 LLM 없음(클라우드 API).
- 웹(8080)은 집 LAN 전용. 외부 공개는 명세의 보안 절 결정 전까지 하지 않는다.

## 작업 규칙

- 사용자에게는 한국어로 답한다. 코드 식별자·주석은 영어, 사용자에게 보이는 문구는 한국어.
- 커밋은 사용자가 요청할 때만 한다. 커밋 메시지에 Claude 공동 저자(Co-Authored-By) 줄을 넣지 않는다.
- 수집한 콘텐츠는 개인 열람용이다. 재배포하지 않고, robots.txt와 요청 간격을 지킨다. 페이월은 우회하지 않는다.
