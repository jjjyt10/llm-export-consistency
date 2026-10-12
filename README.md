# LLM Export Consistency

ChatGPT, Gemini, Claude의 공식 내보내기 자료를 대상으로 구조적 일관성과 관련 파일 간 관계를 검사하는 연구용 코드입니다.

**논문 실험에 사용한 코드 공개 저장소이며, 모든 계정·서비스 버전의 자료에 적용되는 범용 위변조 탐지 도구가 아닙니다.** 불일치가 발견되지 않았다는 결과는 진본 판정이 아닙니다.

## 연구 범위

외부의 신뢰할 수 있는 원본이나 변경 이전의 해시가 없는 상황에서 내보내기 자료 자체로 확인 가능한 불일치와 검사 한계를 분석합니다.

- ChatGPT: 메시지 그래프, JSON–HTML 내장 대화 표현, manifest 목록·크기, 첨부파일·라이브러리 관계
- Claude: 메시지 그래프, 중복 본문, 대화·로그인 기록의 계정 참조
- Gemini: 활동 자료의 형식, 첨부 참조와 실제 파일 존재 및 참조 표현 간 일치

같은 묶음의 중복 자료는 독립적인 신뢰 원본이 아닙니다. Gemini 활동은 다른 서비스의 메시지·대화와 같은 단위로 취급하지 않습니다. 시간정보 이상은 구조적 불일치와 구분하여 해석합니다.

## 환경

- 저자 실행 환경: Windows, Python 3.14.6(실험 기록 기준)
- 외부 패키지 없이 Python 표준 라이브러리 사용
- 다른 Python 버전·운영체제 전체의 호환성을 보장하지 않음
- 코드의 검사·감사에는 `assert`가 사용되므로 `python -O`로 실행하지 않음

## 코드 구성

| 경로 | 용도 |
|---|---|
| 각 서비스의 `scripts/validate_exports.py` | 동일한 v0.2 JSON 내부 검증기 |
| `chatgpt/scripts/run_chatgpt_eval.py` | 기존 ChatGPT EVAL 변경 실험 |
| `chatgpt/scripts/chatgpt_crossfile.py` | JSON–HTML 및 manifest 교차검증·변경 실험 |
| `chatgpt/scripts/chatgpt_attachment_eval.py` | 연구용 첨부파일의 참조·메타데이터·크기 검사 및 변경 실험 |
| `chatgpt/scripts/run_chatgpt_parent_eval.py` | 실제 부모 연결 변경과 JSON–HTML 동시 수정 비교 |
| `claude/scripts/run_claude_eval.py` | 기존 Claude EVAL 변경 실험 |
| `claude/scripts/run_claude_parent_eval.py` | 실제 존재하는 부모로의 비순환·순환 변경 |
| `claude/scripts/claude_metadata_check.py` | 대화·로그인 자료의 계정 참조 확인 |
| ChatGPT·Claude의 `scripts/run_position_eval.py` | 첫·중간·마지막 답변 삭제 비교 |
| `gemini/scripts/run_gemini_eval.py` | 기존 Gemini EVAL 활동 변경 실험 |
| `gemini/scripts/gemini_crossfile.py` | 첨부 참조와 파일 간 교차검증·변경 실험 |
| `gemini/scripts/summarize_gemini_sup.py` | SUP 활동의 URL 연관 및 중복 제거 집계 |

## 입력 자료와 재현 범위

개인정보가 포함될 수 있는 공식 내보내기 원본, 변조 사본 및 상세 보고서는 포함하지 않습니다. 따라서 저장소 다운로드만으로 논문의 모든 수치를 재실행할 수는 없습니다. 현 버전에는 별도의 합성 예제 데이터도 포함되어 있지 않습니다.

각 서비스 폴더 안에 로컬 `input` 폴더를 만들고 본인이 적법하게 확보한 자료의 복사본을 둡니다. 원본은 별도로 보존합니다. 아래 파일명은 실행 예시용 이름이며 공식 다운로드 파일명을 뜻하지 않습니다.

| 서비스 | 입력 예시 | 실제 자료 |
|---|---|---|
| ChatGPT | `input/chatgpt_eval_export.json` | 평가 대화를 포함한 `conversations.json` |
| ChatGPT | `input/chatgpt_eval_archive.zip` | 대화 JSON·HTML·root manifest가 포함된 원본 ZIP 복사본 |
| ChatGPT | `input/chatgpt_sup_paid_archive.zip` | 저자의 특정 첨부 실험 ZIP 복사본(해시 제한 있음) |
| Claude | `input/claude_eval_export.json` | 평가 대화를 포함한 대화 JSON |
| Claude | `input/claude_sup_conversations.zip`, `input/claude_sup_metadata.zip` | 대화 ZIP 및 사용자·로그인 메타데이터 ZIP |
| Gemini | `input/gemini_eval_export.json` | Takeout의 Gemini 활동 JSON |
| Gemini | `input/gemini_sup_archive.zip` | 활동 JSON과 첨부파일을 함께 포함한 Takeout ZIP |
| Gemini | `input/gemini_sup_export.json` | SUP 시나리오를 포함한 활동 JSON |

### 연구 자료에 종속된 조건

- EVAL 실험은 서비스별 사전 정의된 9개 제목 또는 태그를 선택합니다. ChatGPT는 `EVAL-CGPT-01`부터 `09`까지 사용하되 `03`은 `EVAL-CGPT-03-R1`입니다. Claude는 `EVAL-CLAUDE-01`부터 `09`, Gemini는 해당 `EVAL-GEMINI` 태그와 URL 연관 조건을 사용합니다.
- 삭제 위치 실험은 일반 대화 3개만 선택하며, 선형 연결 구조와 답변 3개를 요구합니다.
- 첨부 변경 실험은 `SUP-CGPT-04~06` 또는 `SUP-GEMINI-04~06`의 특정 구조·첨부 조건을 요구합니다. 파일명, 내용, 선택 정책 등 상세 조건은 해당 코드에 정의되어 있습니다.
- `chatgpt_attachment_eval.py`는 저자가 검토한 특정 원본 ZIP의 SHA-256과 일치해야 실행됩니다. 이 원본은 공개하지 않으므로 다른 ZIP을 넣으면 중단되는 것이 정상입니다. 현 버전은 해당 실험의 구현 공개용이며 임의 자료에 대한 즉시 실행을 지원하지 않습니다.
- 다른 자료로 확장하려면 수집 구조와 선택 조건을 별도로 검토하고 새로운 버전으로 관리해야 합니다. 보호 조건을 단순 삭제하여 원래 실험과 동일하다고 주장해서는 안 됩니다.

## 실행 방법

각 명령은 **저장소 루트가 아닌 해당 서비스 폴더에서** 실행합니다. 경로의 `/`는 Windows Python에서도 사용할 수 있습니다. 입력이 없으면 `--help`로 사용법만 확인할 수 있습니다.

### ChatGPT

저장소 루트에서 `cd chatgpt` 후 필요한 명령을 하나씩 실행합니다.

```console
python scripts/validate_exports.py chatgpt input/chatgpt_eval_export.json
python scripts/run_chatgpt_eval.py input/chatgpt_eval_export.json
python scripts/chatgpt_crossfile.py validate input/chatgpt_eval_archive.zip
python scripts/chatgpt_crossfile.py experiment input/chatgpt_eval_archive.zip
python scripts/run_chatgpt_parent_eval.py input/chatgpt_eval_archive.zip
python scripts/run_position_eval.py chatgpt input/chatgpt_eval_export.json
```

다음 두 명령은 위에 설명한 특정 첨부 실험 원본을 요구합니다.

```console
python scripts/chatgpt_attachment_eval.py validate input/chatgpt_sup_paid_archive.zip
python scripts/chatgpt_attachment_eval.py experiment input/chatgpt_sup_paid_archive.zip
```

### Claude

저장소 루트에서 `cd claude` 후 실행합니다.

```console
python scripts/validate_exports.py claude input/claude_eval_export.json
python scripts/run_claude_eval.py input/claude_eval_export.json
python scripts/run_claude_parent_eval.py input/claude_eval_export.json
python scripts/run_position_eval.py claude input/claude_eval_export.json
python scripts/claude_metadata_check.py input/claude_sup_conversations.zip input/claude_sup_metadata.zip
```

### Gemini

저장소 루트에서 `cd gemini` 후 실행합니다.

```console
python scripts/validate_exports.py gemini input/gemini_eval_export.json
python scripts/run_gemini_eval.py input/gemini_eval_export.json
python scripts/gemini_crossfile.py validate input/gemini_sup_archive.zip
python scripts/gemini_crossfile.py experiment input/gemini_sup_archive.zip
python scripts/summarize_gemini_sup.py input/gemini_sup_export.json
```

실행별 출력 위치는 터미널의 `Report` 또는 `Output`에서 확인합니다. 실험 스크립트는 보통 `results` 아래 새 폴더에 사본·변경 기록·보고서·집계 파일을 저장합니다. 입력 자료를 연구 코드 ZIP과 혼동하지 않도록 합니다.

## 코드 해시와 줄바꿈

일부 실험 스크립트는 검증기 파일의 바이트 해시를 확인합니다. 세 서비스의 `validate_exports.py`는 다음 SHA-256을 공유합니다.

```text
71a54078a3b79d86027187267c07117fbec3928640bbd31f18079daf18bc744c
```

ChatGPT 부모 참조 실험은 `chatgpt_crossfile.py`의 해시도 확인합니다.

```text
0854531580a8765a7d51eb5e0857dd8479134e274028fed17f95cc42e677aa3f
```

줄바꿈·공백 변경만으로도 해시가 달라질 수 있습니다. `.gitattributes`에서 Python 파일의 LF 줄바꿈을 지정했습니다. 불일치가 발생하면 실제 코드와 줄바꿈을 확인하고, 기대 해시를 임의로 덮어쓰지 않습니다. 수정이 필요하면 기존 실험 버전을 보존한 별도 변경으로 기록합니다.

## 결과 해석

| 상태 | 의미 |
|---|---|
| `inconsistency_found` | 정의된 규칙의 불일치 발견 |
| `no_inconsistency_found` | 수행한 비교에서 불일치 미발견(진본 판정 아님) |
| `incomplete` | 필요한 정보가 없어 일부 비교 수행 불가 |
| `not_supported` | 해당 서비스에서 현재 규칙 미지원 |
| `no_eligible_data` | 해당 규칙의 적용 대상 없음 |

`checked`는 규칙별 비교 수이므로 독립 표본 수가 아닙니다. `blocked`는 비교 불가, `excluded`는 규칙상 제외된 항목 수입니다. 발견과 비교 불가가 같은 규칙에 함께 존재할 수 있으므로 상태뿐 아니라 세부 수치도 확인합니다.

v0.2는 시간정보 규칙도 공통 상태로 출력하지만, 논문 집계에서는 `timestamp_format`과 `parent_time_order`를 시간 경고로 구분합니다. 기존 EVAL 실행기의 `detected` 수치를 모두 구조적 탐지라고 해석하지 않습니다. 동일 사본에서 여러 규칙이 발견한 결과를 독립 사례로 합산하지 않습니다. 서로 다른 모듈의 B1·A1 등 조건명은 모듈과 함께 해석합니다.

검사 프로필의 한계:
- JSON–HTML 비교는 HTML 내장 데이터의 비교이며 화면 표시 동일성 검사가 아닙니다.
- ChatGPT 첨부 실험의 통과를 JSON–HTML 검사 통과로 확대하지 않습니다.
- Gemini의 첨부 경로 일치는 첨부 내용의 진정성을 보장하지 않습니다.
- Claude 계정 참조 일치는 특정 로그인과 대화의 귀속이나 본문 진정성을 입증하지 않습니다.
- 소규모 합성 시나리오 및 동일 대화에서 파생된 사본을 사용합니다. 블라인드 평가나 독립 표본 180개로 설명하지 않습니다.

## 데이터 보호

`.gitignore`는 로컬 입력·원본·결과·변조 폴더 및 ZIP·첨부 바이너리를 제외하도록 설정했습니다. 다만 이미 추적 중인 파일이나 웹 업로드를 자동으로 정리하는 기능은 아닙니다. 커밋·업로드 전 파일 목록을 확인해야 합니다.

변조 사본에도 변경 대상 이외의 개인 대화가 그대로 남을 수 있습니다. 원본, 사본, 변경 기록, 상세 보고서를 자동으로 공개하지 마세요.

## 개발 및 검토

스크립트 작성에는 LLM을 보조적으로 활용했습니다. 실험에서는 원본 보존, 변경 범위 감사, 코드·입력 해시 기록 및 대표 사례의 변경 전후 데이터와 검사 결과 대조를 수행했습니다. 이러한 확인은 모든 코드 경로의 정확성 또는 포렌식 도구 인증을 의미하지 않습니다.

이 저장소는 논문 실험 코드와 실행 조건을 공개하기 위한 것입니다. 논문 인용 시 실제 사용한 커밋을 지정합니다. 라이선스가 추가되기 전에는 별도 오픈소스 라이선스가 부여되었다고 해석하지 않습니다.
