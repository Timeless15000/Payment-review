# payment-review 대시보드 — 설치 가이드 (Brian용)

직원 outstanding-dashboard 방식 그대로 + **Payment Review 탭** 추가 버전.
링크만 열면 항상 최신 (주중 9시/1시 자동 갱신, 다운로드 없음).

완성 주소: **https://timeless15000.github.io/payment-review/**
(비밀번호는 직원 대시보드와 동일)

---

## 1단계 — 파일 올리기 (GitHub Desktop 추천)

1. GitHub Desktop → File → Clone repository → `Timeless15000/payment-review` 선택 → Clone
2. 이 zip 안의 **모든 파일·폴더**를 그 클론 폴더에 복사
   (`.github` 폴더까지 꼭 같이! 이게 자동 갱신 스케줄임)
3. GitHub Desktop → Summary에 "initial" 입력 → **Commit to main** → **Push origin**

(웹으로 올리려면: 레포 → Add file → Upload files로 드래그.
단, `.github/workflows/update.yml`은 웹에서는 Add file → **Create new file**로
경로를 `.github/workflows/update.yml` 이라고 직접 타이핑해서 내용 붙여넣기.)

## 2단계 — Xero 앱 + REFRESH TOKEN (1회)

직원이 만든 앱을 재사용해도 되고(Client ID/Secret을 받아오면 됨),
직접 만들어도 됨:

1. https://developer.xero.com/app/manage → **New app**
   - 이름: Payment Review Dashboard / 종류: **Web app**
   - Redirect URI: `http://localhost:8080/callback`
2. 생성 후 **Client ID** 복사, **Generate a secret** → **Client Secret** 복사
3. 클론 폴더에서 **GET_TOKEN.bat 더블클릭** → ID/Secret 붙여넣기
   → 브라우저 열리면 Xero 로그인 → **4개 법인(TPM, SOR, TCC, TF/Teamforce) 모두 체크** → Allow
4. 검은 창에 나오는 긴 **REFRESH TOKEN** 복사

※ 주의: 직원 대시보드의 기존 토큰은 재사용 불가 (이 버전은 이메일·연락처
권한이 추가로 필요해서 새로 발급해야 함).

## 3단계 — GitHub에 비밀값 3개 넣기

레포 → **Settings → Secrets and variables → Actions → New repository secret** (3번):

| 이름 | 값 |
|------|----|
| `XERO_CLIENT_ID` | Client ID |
| `XERO_CLIENT_SECRET` | Client Secret |
| `XERO_REFRESH_TOKEN` | 2단계의 토큰 |

## 4단계 — 첫 실행

레포 → **Actions** 탭 → 워크플로 사용 동의 버튼이 보이면 클릭 →
**Update dashboard** → **Run workflow** → 초록 체크 뜰 때까지 ~1분.

## 5단계 — 웹페이지 켜기

레포 → **Settings → Pages** → Source: **Deploy from a branch**,
Branch: **main**, 폴더: **/(root)** → Save.
1~2분 후 https://timeless15000.github.io/payment-review/ 접속.

---

## 이후엔 전부 자동

- 법인 4개: SOR / TCCS / TPM / TF
- 주중 시드니 9시/1시쯤 자동 갱신 (즉시 갱신: Actions → Run workflow)
- 토큰은 실행 때마다 스스로 갱신 (token.json)

## Payment Review 탭 사용법

- 상단 **Payment Review** 버튼 → XERO 바의 Shift+F23과 같은 분류:
  Skipped Payment(빨강) / 3+ months(주황) / 2+ months(노랑) / Recent(파랑)
- 오른쪽 **Ref filter** 기본값 `ww1, ww2, ww3` (비우면 전체)
- **Excel** = CSV 다운로드 · 고객 줄의 이메일 클릭 = 메일 쓰기
- **Download PDFs**: 체크 후 누르면 Xero 탭이 열려 자동 다운로드
  (그 법인에 로그인 + XERO 바 설치된 PC에서만 동작)

## 참고

- Terminated 목록은 `terminated_seed.json`에서 읽음 (금액·paid 여부는 매번
  최신 데이터로 자동 계산). 해지 고객 추가/삭제는 이 파일 수정 후 push.
- 레포가 Public이면 페이지 소스에 고객명·금액이 들어감 (직원 레포와 동일한
  조건, 비밀번호 화면은 있음). 완전 비공개가 필요하면 따로 상의.
