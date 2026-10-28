# ☁️ PC 없이 쓰기 — GitHub + Streamlit Cloud 설정 안내 (개발 지식 없이 따라하기)

> 대상 저장소: **https://github.com/ogeunho011-dotcom/short-dashboard** (이미 만들어져 있음 · 비공개 · 기본 브랜치 `main`)
> 다 하고 나면 이렇게 됩니다.
> - 📱 **폰 알림**: GitHub 가 미국 장 시간 동안 20분마다(프리·애프터는 1시간마다) 급등 신호를 확인하고, 신호가 있으면 ntfy 앱으로 알림이 옵니다. **PC를 꺼 두어도 됩니다.**
> - 📊 **대시보드**: `https://(이름).streamlit.app` 주소로 폰에서 언제든 열립니다.
> - 🔄 **데이터 갱신**: 매일 한국 시간 오전 10시 20분쯤(미국 장 마감 후) 자동으로 갱신됩니다.
>
> 걸리는 시간: 처음 한 번 30~40분 정도. 돈은 들지 않습니다 (무료 한도 안에서 동작하도록 맞춰 둠, 아래 ⑨ 참고).

---

> ✅ **2026-10-28 에 이미 끝내 둔 것** (다시 할 필요 없음)
> - ① 파일 올리기 — 코드 전체가 `main` 브랜치에 올라가 있습니다.
> - ② `NTFY_TOPIC` Secret — 무작위 주제 이름으로 등록됨 (값은 따로 전달받은 주제 이름. 폰 ntfy 앱에서 그 이름을 구독하세요).
> - ③-A 씨앗 DB — Releases 의 `db-latest` 에 `shortdash.sqlite.gz` 가 올라가 있습니다. **지우지 마세요.**
> - ③·④ Actions 켜기 + daily·alerts 1회 실행 확인.
>
> 👉 **남은 일: ⑤ 토큰 만들기 → ⑥ Streamlit Cloud 배포 → ⑦ 폰에서 ntfy 구독.** 아래 ①~④ 는 처음부터 다시 만들 때만 참고하세요.

## ① 파일 올리기 (저장소는 이미 있음)

1. 받은 `short-dashboard.zip` 을 PC에서 **압축 해제**합니다. 폴더 안에 `app.py`, `core`, `scripts`, `.github` … 가 보여야 합니다.
   - ⚠️ `.github`, `.streamlit`, `.gitignore` 처럼 **점(.)으로 시작하는 폴더·파일은 숨김**일 수 있습니다.
     Windows: 탐색기 → 보기 → "숨긴 항목" 체크 / Mac: Finder 에서 `Cmd + Shift + .`
2. https://github.com/ogeunho011-dotcom/short-dashboard 접속 → **Add file → Upload files**.
3. 압축을 푼 폴더 **안의 내용 전체**(폴더 자체가 아니라 그 안의 파일·폴더들)를 끌어다 놓습니다. `.github` 폴더도 꼭 포함하세요. (끌어다 놓기가 숨김 폴더를 빠뜨리면 아래 "확인"에서 알 수 있습니다.)
4. 아래 **Commit changes** 클릭.
5. **확인**: 저장소 첫 화면에 `.github/workflows` 폴더가 보이고, 그 안에 `alerts.yml`, `daily.yml` 두 파일이 있어야 합니다.
   없으면 **Add file → Create new file** 에서 이름 칸에 `.github/workflows/alerts.yml` 이라고 쓰고, PC의 같은 파일 내용을 복사해 붙여 넣은 뒤 커밋하세요 (`daily.yml` 도 같은 방법).
6. 기존 README 를 덮어쓸지 물으면 덮어써도 됩니다.

> 🔒 비밀값(토큰·주제 이름·비밀번호)은 파일에 들어 있지 않습니다. `.streamlit/secrets.toml.example` 은 **예시**일 뿐이고, 진짜 값은 아래 ②·⑥ 에서 GitHub/Streamlit 의 "Secrets" 칸에만 넣습니다.
> 압축 파일에는 큰 데이터 파일(DB)이 빠져 있습니다 — GitHub Actions 가 만들거나(③), 따로 받은 씨앗 DB 를 올립니다(③-A).

## ② 알림 주제 이름 정하기 + GitHub Secrets

**ntfy 알림 주제(topic)** 는 "알림 받는 채널 이름"입니다. 아무나 이 이름을 알면 알림을 엿볼 수 있으니 **길고 무작위**로 정하세요.
예: `shortradar-` 뒤에 영문·숫자를 16자 이상 아무렇게나 붙이세요 (모양 예: `shortradar-여기에본인만아는16자이상`). **문서의 예시를 그대로 쓰지 말고 직접 만드세요.**
(대시보드 관리 탭 → 📲 폰 알림 (급등 신호) · 토스 링크 → "주제 이름 새로 만들기" 버튼으로 만들어도 됩니다.)

1. 저장소 → **Settings → Secrets and variables → Actions → New repository secret**
2. 다음을 하나씩 추가 (이름은 정확히 대문자 그대로):

| Name | 값 | 필수 |
|---|---|---|
| `NTFY_TOPIC` | 위에서 정한 주제 이름 | ✅ |
| `DASH_URL` | 대시보드 주소 (⑥ 끝난 뒤 추가해도 됨) — 알림의 "대시보드" 버튼 | 선택 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 텔레그램도 받고 싶을 때만 | 선택 |
| `NTFY_SERVER` | 직접 운영하는 ntfy 서버가 있을 때만 (기본 https://ntfy.sh) | 선택 |

## ③ 데이터 만들기 — Actions 켜고 "daily" 먼저 1번

1. 저장소 → **Actions** 탭. "워크플로를 실행할까요?" 같은 안내가 나오면 **I understand my workflows, go ahead and enable them** 클릭.
2. 왼쪽 목록에서 **daily** → 오른쪽 **Run workflow** → 초록 **Run workflow**.
3. 몇 분 뒤 초록 체크 ✅ 가 되면 성공입니다. (저장소 오른쪽 **Releases** 에 `db-latest` 가 생기고 `shortdash.sqlite.gz` 파일이 붙어 있습니다. **지우지 마세요** — 대시보드와 알림이 이 파일을 씁니다.)
   - 빈 상태에서 처음 만들 때 이 PC(테스트 환경)에서는 약 2분 걸렸습니다. GitHub 서버에서는 더 걸릴 수 있습니다 (최대 150분 제한).
   - ⚠️ 빈 상태에서 만든 DB 는 **공매도 거래량 최근 약 1개월치만** 들어 있고, 예측 확률을 보정하는 **검증(백테스트) 결과가 없습니다**. 그래서 아래 ③-A(씨앗 DB)를 권장합니다.

### ③-A (✅ 이미 완료 · 다시 할 필요 없음) 씨앗 DB 올리기 — 지금까지 쌓은 1년 반치 데이터 그대로 쓰기

함께 받은 `shortdash.sqlite.gz`(약 50MB, 공매도 거래량 2025-03 ~ 2026-10 · 검증 결과 포함 · 매매일지·알림 주제 등 개인값은 지움)를 올리면 처음부터 완전한 상태로 시작합니다.

1. 저장소 → 오른쪽 **Releases** → **Create a new release** (이미 `db-latest` 가 있으면 그걸 열고 ✏️ Edit).
2. **Choose a tag** 칸에 `db-latest` 입력 → "Create new tag" 선택. 제목은 아무거나 (예: DB 스냅샷).
3. 아래 "Attach binaries" 칸에 `shortdash.sqlite.gz` 를 끌어다 놓기 (이미 같은 이름이 있으면 먼저 그 파일 옆 🗑 로 지우고 올림).
4. **Publish release** (또는 Update release).
5. 그다음 Actions → **daily → Run workflow** 를 한 번 더 돌리면 씨앗 DB 위에 최신 데이터가 이어서 쌓입니다.

## ④ 알림 테스트 — "alerts" 를 test 로 1번

1. Actions → 왼쪽 **alerts** → **Run workflow** → **"테스트 알림만 보내기"(test) 체크** → Run.
2. ✅ 가 되면, ⑦ 에서 ntfy 앱을 구독한 폰에 테스트 알림이 옵니다. (구독을 먼저 해 두면 바로 확인 가능)
3. ❌ 빨간색이고 로그에 `NTFY_TOPIC` 이야기가 있으면 ② 의 Secret 이름/값을 확인하세요.
4. 이후에는 아무것도 안 해도 **월~금 뉴욕 시각 04:00~20:00** 동안 자동으로 돕니다. 그 외 시간에 예약 실행되면 첫 단계에서 바로 끝납니다(정상).
   - "장 시간 아니어도 실행"(force) 체크로 돌리면 장 외 시간에도 실제 스캔을 해 볼 수 있습니다.
5. 알림 기록·채점은 자동으로 만들어지는 **`alert-data` 브랜치**에 저장됩니다 (main 은 건드리지 않음 → 대시보드가 쓸데없이 재시작되지 않음).

## ⑤ 대시보드용 GitHub 토큰 만들기 (읽기/쓰기 · 이 저장소만)

대시보드가 ① 최신 DB(릴리스) ② 알림 기록(alert-data 브랜치)을 읽고 ③ 관리 탭에서 바꾼 알림 설정을 GitHub 쪽에도 저장하려면 토큰이 필요합니다.

1. GitHub 오른쪽 위 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Token name: `short-dashboard` / Expiration: 원하는 기간 (만료되면 새로 만들어 ⑥ 의 값만 바꾸면 됨)
3. **Repository access → Only select repositories → `ogeunho011-dotcom/short-dashboard`** 하나만 선택
4. **Permissions → Repository permissions → Contents: Read and write** (나머지는 건드리지 않음 · Metadata: Read 는 자동)
5. **Generate token** → `github_pat_...` 로 시작하는 값을 **바로 복사** (다시 안 보여줌). 어디에도 붙여 넣지 말고 ⑥ 의 Secrets 칸에만 넣으세요.

## ⑥ Streamlit Community Cloud 에 대시보드 올리기

1. https://share.streamlit.io 접속 → **Continue with GitHub** 로 로그인 → 비공개 저장소 접근 권한을 묻으면 허용.
2. **Create app → Deploy a public app from GitHub**(문구는 바뀔 수 있음; "From existing repo") 선택.
3. Repository: `ogeunho011-dotcom/short-dashboard` / Branch: `main` / Main file path: `app.py`
4. App URL 은 원하는 이름으로 (예: `ogeunho011-short-dashboard`).
5. **Advanced settings**:
   - Python version: **3.13**
   - Secrets 칸에 아래를 붙여 넣고 값만 바꾸기 (`.streamlit/secrets.toml.example` 과 같은 내용):
     ```toml
     NTFY_TOPIC = "②에서 정한 주제 이름 (GitHub 것과 똑같이)"
     GH_REPO = "ogeunho011-dotcom/short-dashboard"
     GH_TOKEN = "⑤에서 복사한 github_pat_..."
     APP_PASSWORD = "원하는 비밀번호"   # 선택 — 지우면 비밀번호 화면 없음
     # DASH_URL = "https://ogeunho011-short-dashboard.streamlit.app"
     ```
6. **Deploy**. 첫 실행은 패키지 설치 + DB 다운로드(약 50MB)로 몇 분 걸립니다. 이후에는 15분마다 새 DB 가 있는지 확인해서 받아 옵니다.
7. 주소가 정해지면 ② 의 GitHub Secret `DASH_URL` 에도 넣어 두면 알림의 "대시보드" 버튼이 이 주소로 열립니다.

**누가 볼 수 있나?** 비공개 저장소에서 올린 앱은 **비공개 앱**입니다 — Streamlit 에 로그인한 본인(및 앱 설정 → Sharing 에 초대한 이메일)만 볼 수 있습니다. 폰에서 처음 열 때 구글 계정 또는 이메일 링크로 로그인합니다. 무료 계정은 비공개 앱을 **1개**까지 만들 수 있습니다. `APP_PASSWORD` 를 넣으면 한 겹 더 잠깁니다.

## ⑦ 폰 설정 — ntfy 구독 + 홈 화면에 대시보드

**ntfy (알림)**
1. 앱 설치: 안드로이드 Play 스토어 / 아이폰 App Store 에서 **ntfy** 검색.
2. 앱 → **+** (Subscribe to topic) → 주제 이름 칸에 ② 의 이름 그대로 → 서버는 기본(ntfy.sh) → Subscribe.
3. 알림을 누르면 **토스증권 해당 종목 페이지**가 열리는 링크가 들어 있습니다 ("토스에서 열기" 버튼).
   - 아이폰은 ntfy 앱 설정에서 알림 허용을 꼭 켜세요.

**홈 화면 바로가기 (대시보드)**
- 아이폰 Safari: 대시보드 주소 열기 → 공유 버튼 → **홈 화면에 추가**
- 안드로이드 Chrome: 주소 열기 → ⋮ 메뉴 → **홈 화면에 추가**

## ⑧ 평소에 할 일

- 없습니다. 알림 조건(확률 기준·방해 금지 시간·알림 종류 등)은 대시보드 **관리 탭 → 📲 폰 알림 (급등 신호) · 토스 링크** 에서 바꾸고 저장하면 GitHub 쪽(alert-data 브랜치의 `data/alerts/alert_cfg.json`)에도 저장되어 다음 스캔부터 적용됩니다. (주제 이름은 보안상 파일에 저장하지 않습니다 — 바꾸려면 GitHub Secret 과 Streamlit Secrets 두 곳 모두 바꾸세요.)
- 보낸 알림과 자동 채점 결과(10거래일 뒤 성공/실패)는 **오늘 탭의 알림 기록**, **관리·타임머신 탭의 "실전 알림 성적"** 에 보입니다.

## ⑨ 꼭 알아둘 한계 (솔직하게)

- **Streamlit 앱 잠자기**: 12시간 동안 아무도 안 열면 앱이 잠듭니다. 다시 열면 "Wake up" 버튼 → 1분 안팎 기다리면 깹니다. **알림은 GitHub Actions 가 보내므로 앱이 잠들어도 알림은 옵니다.**
- **예약 실행 지연**: GitHub 의 예약 실행은 몇 분~수십 분 늦거나, 붐비는 시간엔 **가끔 건너뛸 수 있습니다**. 알림은 "실시간 체결 알림"이 아니라 20분 간격 점검입니다.
- **무료 시간 한도 (비공개 저장소 월 2,000분)** — 추정치:
  - alerts: 평일 하루 33회 실행(장 외 시간에 걸린 회차는 첫 단계에서 바로 끝남). 실제 스캔 회차 약 2분(설치·DB 받기 포함 추정), 바로 끝나는 회차 1분으로 계산하면 `32×2 + 1 = 65분/일 × 21.7일 ≈ 1,410분/월`.
  - daily: 이어서 갱신하는 경우 이 PC에서 갱신 자체 29초 + 설치·업로드 ≈ 2~3분 → `≈ 50~70분/월`.
  - 합계 **약 1,500분/월 (한도 2,000분 안)**. 실제 사용량은 GitHub → Settings → Billing 에서 확인하세요. 모자라면 `alerts.yml` 맨 위 cron 의 `5,25,45` 를 `5,35` 로 바꾸면 정규장 30분 간격이 됩니다. (저장소를 공개로 바꾸면 무제한이지만, 그러면 코드가 누구에게나 보입니다.)
- **휴장일**: 미국 공휴일에도 예약 실행은 돌지만 새 데이터가 없어 알림이 거의 없습니다 (시간만 조금 씀).
- **yfinance 제한**: 무료 데이터 소스라 GitHub 서버 IP 가 일시적으로 막히면(“Too Many Requests”) 그 회차는 데이터가 비어 알림이 안 올 수 있습니다.
- **토스 링크**: 링크 주소 형식·종목코드 응답(200)은 확인했지만, **실제 폰에서 토스 앱이 바로 열리는지는 테스트하지 못했습니다.** 앱 대신 웹이 열리면 관리 탭 → 📲 폰 알림 → "토스 링크 방식"을 "앱 바로 열기 (supertoss://)" 또는 "웹" 으로 바꿔 보세요. 유니버스 2,520종목 중 93종목은 토스 종목코드를 찾지 못해 **토스 홈**으로 연결됩니다.
- **PC 방식도 그대로 됩니다**: 집 PC에서 `run.bat`/`run.command`(대시보드), `run_alerts.bat`/`run_alerts.command`(알림 반복 실행)도 계속 쓸 수 있습니다. 단, 클라우드와 PC를 **동시에** 알림으로 돌리면 같은 알림이 두 번 올 수 있으니 하나만 쓰세요.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| Actions 탭에 alerts/daily 가 없음 | `.github/workflows/` 폴더가 안 올라간 것 → ① 의 5번 |
| alerts 실행 로그에 "DB 스냅샷이 아직 없습니다" | ③ daily 먼저 실행(또는 ③-A) |
| 알림이 안 옴 | ntfy 앱의 주제 이름 = GitHub Secret `NTFY_TOPIC` 인지 (대소문자·하이픈까지), 관리 탭의 "알림 켜기"·"방해 금지" 시간 |
| 대시보드에 "데이터 없음"/오래된 데이터 | Streamlit Secrets 의 `GH_REPO`, `GH_TOKEN`(만료·권한 Contents Read and write) |
| 관리 탭 저장 후 "⚠ GitHub 반영 실패" | 토큰 권한이 Read-only 인지 확인 |
