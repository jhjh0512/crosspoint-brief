# crosspoint-brief

CrossPoint 펌웨어를 쓰는 E-ink 리더(Xteink X4)를 위한 개인 아침 브리핑 발행 서버입니다.
여러 입력원에서 콘텐츠를 모아 매일 정해진 시각에 EPUB 한 권으로 만들고, 기기는 기존 OPDS 브라우저로 받아 갑니다.

설계 전체는 v0 명세 문서(Claude Docs: "E-ink 개인 출판 플랫폼 v0 명세")를 따릅니다.

## 현재 범위: P0-1

| 포함 | 아직 없음 (다음 단계) |
| --- | --- |
| 커넥터 틀 + RSS·Atom 커넥터 | 웹 페이지 목록 커넥터 (RSSHub, LLM 추출) |
| 공통 ContentItem 저장 (SQLite) | LLM 단계 (보강·분류·묶기·선별·요약·편집·검증) |
| 1차 거르기, 규칙 기반 선별·요약·편집 | Synology 웹 관리 화면 (지금은 `config.toml`) |
| CrossPoint용 EPUB 생성, OPDS 피드 | 표지 대시보드, 원문 QR |
| 앱 내부 스케줄러 (수집 1시간, 발행 06:30, 재시도 07:00) | P1 기기 동기화 API (manifest·ACK) |

LLM이 없으므로 명세의 규칙 대체가 그대로 동작합니다. 선별은 점수·최근성 순, 요약은 입력원이 준 요약(없으면 앞 3문장 발췌), 편집은 기본 순서와 템플릿 문구입니다. 브리프의 "발행 정보" 장에 어떤 단계가 규칙으로 대체됐는지 표시됩니다.

## 로컬에서 실행

[uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync
cp config.example.toml config.toml
uv run brief collect      # 입력원을 한 번 가져옴
uv run brief publish      # 오늘 브리프를 만듦 (이미 있으면 --force)
uv run brief serve        # http://<PC IP>:8080/opds.xml 로 제공
uv run brief status       # 입력원 상태, 최근 실행, 발행물 목록
uv run brief run --serve 8080   # 스케줄러 + 파일 제공 (개발용)
```

테스트: `uv run pytest`, 린트: `uv run ruff check .`

## 기기에서 받아 보기 (P0)

1. PC와 X4를 같은 Wi‑Fi에 연결하고 `uv run brief serve`를 실행합니다.
2. X4의 OPDS 설정에 서버를 추가합니다. 주소는 `http://<PC 또는 NAS IP>:8080/opds.xml`입니다.
3. 홈 → OPDS 브라우저 → 서버를 고르면 오늘 브리프가 보입니다. 선택하면 받아서 엽니다.

EPUB 링크는 반드시 `/`로 시작하는 절대 경로입니다. CrossPoint의 `UrlUtils::buildUrl`은 상대 경로를 피드 주소 뒤에 `/`만 붙여 잇기 때문입니다.

## Synology(XPEnology)에 배포

```bash
mkdir -p config data
cp config.example.toml config/config.toml
docker compose up -d --build
```

- `brief` 컨테이너: 스케줄러. `TZ=Asia/Seoul`이 설정돼 있습니다.
- `web` 컨테이너: nginx가 `data/www`를 8080 포트로 제공합니다. 이 포트는 집 LAN에서만 쓰고 외부에 열지 않습니다.
- G4600은 AVX가 없습니다. 이 이미지는 AVX가 필요한 패키지를 쓰지 않습니다.

## 폴더 구조

```
src/brief/
  config.py            설정 (P0-3에서 웹 관리 화면으로 이전)
  models.py            ContentItem, Publication 등 공통 형식
  db.py                SQLite: 항목, 입력원 상태, 발행물, 실행 기록
  urls.py              URL 정규화 (입력원 간 중복 판단)
  connectors/          커넥터 유형. 새 유형 = 클래스 하나 + 등록 한 줄
  pipeline/            collect → select → compose → publish
  render/              sanitize (HTML → XHTML), epub, opds
  scheduler.py         앱 내부 스케줄러
  serve.py             개발용 정적 서버 (운영은 nginx)
data/                  brief.db, www/opds.xml, www/publications/*.epub
```

## CrossPoint 호환 규칙

- 장(chapter)은 expat으로 파싱되며 `XML_GE=0`이라 이름 있는 엔티티(`&nbsp;` 등)를 쓸 수 없습니다. sanitizer가 모든 엔티티를 문자로 바꾸고 `& < > "`만 이스케이프합니다.
- OPDS는 `application/epub+zip` 획득 링크만 책으로 인식합니다.
- 기사 하나가 spine 항목 하나입니다. nav와 NCX를 모두 넣습니다.
- 폰트는 넣지 않습니다. 기기에 설치된 SD CJK 폰트를 씁니다.
- 같은 발행물은 같은 바이트로 만들어집니다(zip 순서·시각 고정). P1의 SHA256 검증에 그대로 씁니다.
