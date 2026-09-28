# 공통 chrome 시각 기준 이미지

내비게이션과 푸터는 모든 페이지에서 같아야 합니다. `scripts/check_site_ui.py` 는 구조·목적지·계산된 스타일을 검사하는 **사이트 가디언**과 함께, 아래 스크린샷을 승인된 기준 이미지와 비교합니다.

| 캡처 | 범위 |
|------|------|
| `nav` | 고정 상단 내비 전체 |
| `footer` | 푸터 전체 |
| `footer-context` | 푸터 바로 위 180px + 푸터 전체. 한 페이지에서만 푸터가 따로 떨어진 판처럼 보이는 문제(2026-09)를 잡기 위한 캡처 |

- 페이지: `index`, `ggongbab`, `choose`, `mukbang`, `event`, `food`, `history`. 한국어·영어, 1440×900·390×844. 파일 이름은 `<page>-<lang>-<width>-<part>.png`.
- 결정성: 오프라인(외부 폰트·서비스 차단), 브라우저 시계 고정(`2026-09-28T10:00+09:00`), 생성 데이터 대신 고정 fixture, 애니메이션·전환 끔, 2% 필름 그레인 오버레이 숨김.
- 비교: 크기가 같아야 하고, 채널 차이가 24/255 를 넘는 픽셀이 0.2% 이하여야 통과합니다.

## 플랫폼별 기준 세트

글자 래스터화는 OS와 브라우저 빌드마다 달라서, 서로 다른 환경의 픽셀은 비교하지 않습니다. 기준은 환경마다 따로 두고, 각 세트에 승인 메모(`BASELINES.json`)가 있습니다.

| 세트 | 환경 | 쓰는 곳 |
|------|------|---------|
| `tests/visual/chrome/windows-chrome/` | 이 저장소의 Windows 작업 환경, 설치된 Chrome | 로컬 게이트 (`python scripts/check_site_ui.py`) |
| `tests/visual/chrome/linux-chromium/` | `mcr.microsoft.com/playwright/python:v1.63.0-noble-amd64` (digest 고정), 내장 Chromium | CI `ui-guardian` 의 `visual-guardian` job |

`BABDODUK_BROWSER` (`chrome` 기본, CI 는 `chromium`)와 OS 가 세트를 고릅니다. 세트가 없는 환경은 “no approved baseline” 으로 실패합니다.

## CI

`.github/workflows/ui-guardian.yml` 이 HTML·CSS·JS·이미지·`shared/`·검사 스크립트·기준 이미지가 바뀔 때마다 실행됩니다(생성 데이터만 바뀐 bot push 에는 실행되지 않음).

1. `chrome-sync`: `python scripts/sync_site_chrome.py --check`
2. `visual-guardian`: 고정 컨테이너에서 `python3 scripts/check_site_ui.py --chrome-only` (가디언 + 시각 비교)

실패하면 `.local/visual-diff/` 가 `visual-diff-<run id>` artifact 로 올라갑니다. 실패한 이미지마다 실제 렌더(`*.png`)와 차이 이미지(`*.diff.png`)가 있고, `SUMMARY.md` 와 job summary 에 페이지·언어·폭·구성요소가 표로 나옵니다. 가디언이 실패해도 시각 비교는 끝까지 돌고, 가디언이 멈춘 페이지의 캡처(`guardian-<page>-<lang>-<width>.png`)와 실패 항목이 같은 표에 들어갑니다. 아티팩트에는 오프라인으로 띄운 공개 페이지의 화면만 담깁니다.

CI 는 기준을 바꾸지 않습니다. `--update-chrome-baselines` 와 `--adopt-chrome-baselines` 는 `CI`/`GITHUB_ACTIONS` 환경에서 스스로 거부합니다.

## 기준 이미지를 바꾸는 조건 (자동 승인 없음)

새 스크린샷으로 기준을 덮어쓰면 회귀를 숨길 수 있습니다. 기준 이미지는 다음이 **모두** 있을 때만 바꿉니다.

1. 의도한 UI 변경이다(작업 브랜치와 커밋이 있다).
2. 그 변경이 babdoduk-lab 에 배포되었다.
3. 소유자가 lab 화면을 보고 검토했다.
4. 소유자가 명시적으로 승인했다.

로컬 세트는 로컬에서 다시 만듭니다.

```powershell
python scripts/check_site_ui.py --update-chrome-baselines --approval "<누가, 언제, 어디서 승인했는지>"
```

CI 세트는 CI 가 렌더링한 이미지를 받아서 채택합니다. 기준이 없거나 달라서 실패한 `ui-guardian` 실행의 artifact 에 그 커밋의 렌더가 들어 있습니다(기준이 없을 때는 84장 전부).

```powershell
gh run download <run id> --name visual-diff-<run id> --dir .local/ci-renders
python scripts/check_site_ui.py --adopt-chrome-baselines .local/ci-renders --platform linux-chromium --approval "<승인 메모와 run id>"
```

- `--approval` 없이는 기준을 쓰지 않습니다. 메모는 세트의 `BASELINES.json` 에 남습니다.
- 채택은 84장 전부가 있을 때만 됩니다. 일부만 바꾸지 않습니다.
- 검사가 실패했을 때 기준을 다시 만들어 “통과”시키지 않습니다. 먼저 차이 이미지로 원인을 확인합니다.
