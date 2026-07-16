# Secure Edge Meeting Transcription

외부 클라우드로 회의 음성을 전송할 수 없는 기업 보안 환경을 가정해, **Jetson Orin Nano 단독으로 한국어 회의 음성을 전사하고 로컬 LLM으로 교정하는 PoC**입니다.

음성은 장비 내부에서만 처리합니다. `faster-whisper`가 음성을 한국어 텍스트로 변환하고, `llama-server`의 OpenAI 호환 API를 호출해 STT 오인식과 문장을 교정합니다. 확장 버전은 한 줄 요약, 결과 백업, 선택적 TTS도 제공합니다.

## 처리 흐름

```text
마이크 입력
   ↓
arecord (16 kHz, mono WAV)
   ↓
faster-whisper (한국어 STT)
   ↓
llama-server (회의록 교정 및 요약)
   ↓
터미널 출력 + 장비 내부 백업 (+ 선택적 TTS)
```

## 주요 파일

| 파일 | 설명 |
| --- | --- |
| `voice_step1.py` | STT → LLM 응답 기본 예제 |
| `voice_step2.py` | Step 1 + TTS 음성 출력 |
| `voice_step3.py` | 과제 기본 구현: STT 원본, LLM 교정 회의록, 처리 시간 및 RTF 출력 |
| `voice_transcription.py` | 개선 구현: 전문용어 컨텍스트, 한 줄 요약, 로컬 백업, 세부 시간 측정, 선택적 TTS |

## 실행 환경

- Jetson Orin Nano 또는 Ubuntu 계열 Linux
- Python 3 가상환경
- 마이크 및 ALSA/PulseAudio
- 로컬에서 실행 중인 `llama-server`
- 기본 STT 모델: Whisper `tiny` (약 75 MB)
- 발표 자료의 최종 선정 LLM: `Qwen/Qwen3.5-2B` 계열 양자화 모델

> `arecord`를 사용하므로 Windows에서 직접 실행하는 용도가 아니라 Jetson/Ubuntu 환경을 기준으로 합니다.

## 1. 환경 설정

저장소로 이동한 뒤 가상환경을 만들고 활성화합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install faster-whisper
```

녹음 명령이 없다면 ALSA 유틸리티를 설치합니다.

```bash
sudo apt update
sudo apt install -y alsa-utils
```

선택 기능을 사용할 때만 해당 패키지를 추가합니다.

```bash
# voice_step2.py에서 Edge TTS를 사용할 때
python -m pip install edge-tts

# voice_step2.py에서 gTTS를 사용할 때
python -m pip install gTTS

# voice_transcription.py에서 MeloTTS를 사용할 때
python -m pip install git+https://github.com/myshell-ai/MeloTTS.git
```

## 2. STT 모델 미리 내려받기

인터넷이 연결된 준비 단계에서 Whisper `tiny` 모델을 캐시에 저장합니다. 이후 PoC 실행 중에는 외부 클라우드로 음성을 보내지 않습니다.

```bash
python - <<'PY'
from faster_whisper import WhisperModel

print("Whisper 모델 준비 중...", flush=True)
WhisperModel("tiny", device="cpu", compute_type="int8")
print("모델 준비 완료")
PY
```

## 3. 로컬 LLM 서버 실행

GGUF 모델과 `llama-server` 실행 파일을 준비한 뒤 터미널 A에서 서버를 시작합니다. 모델 경로는 실제 파일에 맞게 바꾸세요.

```bash
./llama-server \
  -m /path/to/model.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  -c 4096
```

서버 연결을 확인합니다.

```bash
curl http://127.0.0.1:8080/v1/models
```

기본 서버 주소는 `http://127.0.0.1:8080`입니다. 다른 주소나 포트를 사용한다면 `LLAMA_SERVER` 환경 변수를 지정합니다.

## 4. 과제 기본 버전 실행

터미널 B에서 가상환경을 활성화하고 실행합니다.

```bash
source .venv/bin/activate
python voice_step3.py
```

실행 순서는 다음과 같습니다.

1. 첫 번째 Enter를 눌러 녹음을 시작합니다.
2. 아래 공통 대본을 낭독합니다.
3. 두 번째 Enter를 눌러 녹음을 끝냅니다.
4. STT 원본, LLM 교정 회의록, 입력 음성 길이, 처리 시간, RTF를 확인합니다.

### 평가용 공통 대본

> 지금부터 7월 둘째 주 수율 관리 회의를 시작하겠습니다. 먼저 공정팀 보고해 주세요. 공정팀 김민준입니다. 지난주 D2 라인 평균 수율은 92.4%로 전주 대비 1.2%포인트 하락했습니다. 
> 원인은 식각 공정의 과식각으로 웨이퍼 가장자리 다이가 불량 처리된 것입니다. 식각 시간을 3초 단축해 재검증하겠습니다. 다음은 품질팀입니다. 품질팀 이서연입니다.
> 12번 로트에서 파티클 불량이 집중적으로 검출되었습니다. 클린룸 필터 교체 주기를 4주에서 2주로 단축하고, CMP 장비 배기 라인을 점검하겠습니다. 두 안건 모두 승인합니다. 
> 다음 회의는 7월 20일 오전 9시에 진행하겠습니다. 이상으로 회의를 마치겠습니다.

대본은 공백을 제외한 워드 문자 기준 268자입니다.

## 5. 개선 버전 실행

`voice_transcription.py`는 다음 기능을 추가합니다.

- D2 라인, 수율, 식각, 과식각, 웨이퍼, CMP, 파티클, 로트 등 전문용어 컨텍스트
- 교정 회의록의 한 줄 요약
- `~/meet/bak_YYYYMMDD_HHMMSS.txt` 형식의 로컬 결과 백업
- 선택적 원본 WAV 백업
- STT, LLM 교정, 요약, TTS 구간별 시간 측정
- 환경 변수로 STT 모델과 실행 옵션 변경

```bash
source .venv/bin/activate
python voice_transcription.py
```

Whisper `small` 모델로 정확도 개선 효과를 비교하려면 다음과 같이 실행합니다.

```bash
ASR_MODEL=small python voice_transcription.py
```

TTS까지 활성화하려면 다음과 같이 실행합니다.

```bash
ENABLE_TTS=1 python voice_transcription.py
```

## 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `LLAMA_SERVER` | `http://127.0.0.1:8080` | llama-server 주소 |
| `LLM_MODEL_NAME` | 코드 기본값 | 결과 파일에 기록할 LLM 이름 |
| `ASR_MODEL` | `tiny` | faster-whisper 모델 (`tiny`, `small` 등) |
| `ASR_DEVICE` | `cpu` | STT 실행 장치 |
| `ASR_COMPUTE_TYPE` | `int8` | STT 연산 형식 |
| `ASR_BEAM_SIZE` | `5` | 디코딩 beam size |
| `AUDIO_DEV` | `pulse` | `arecord` 및 재생 장치 |
| `N_PRED` | `1024` | 교정 결과 최대 토큰 수 |
| `MEET_SAVE_DIR` | `~/meet` | 결과 저장 경로 |
| `SAVE_AUDIO` | `true` | 원본 WAV 백업 여부 |
| `ENABLE_TTS` | `false` | 요약 TTS 생성 여부 |
| `TTS_DEVICE` | `cpu` | TTS 실행 장치 |
| `TTS_SPEED` | `1.0` | TTS 재생 속도 |

예시:

```bash
LLAMA_SERVER=http://127.0.0.1:8080 \
ASR_MODEL=tiny \
MEET_SAVE_DIR="$HOME/meet" \
python voice_transcription.py
```

## 성능 평가

### 1. 한국어 전사 정확도

공백을 제외한 기준 대본과 출력 결과에서 일치하는 글자 수를 세어 계산합니다.

```text
전사 정확도(%) = 일치 글자 수 / 268 × 100
```

각 후보를 3회씩 측정하고 평균값을 비교합니다. 숫자, 날짜, 장비명과 같은 핵심 정보가 바뀌지 않았는지도 함께 확인하세요.

### 2. 실시간성(RTF)

```text
RTF = 입력 후 교정 출력 완료까지 걸린 시간 / 입력 음성 길이
```

- `RTF < 1.0`: 발화 시간보다 빠르게 처리를 완료
- 값이 작을수록 실시간성이 우수

발표 자료의 3회 평균 결과는 다음과 같습니다.

| 후보 | 평균 전사 정확도 | 평균 RTF |
| --- | ---: | ---: |
| A: blossom-8B 계열 | 79.64% | 0.52 |
| B: Qwen/Qwen3.5-2B | **90.30%** | **0.31** |
| C: kanana-nano-2.1b-instruct | 88.47% | 0.32 |

정확도와 실시간성을 함께 고려해 후보 B인 `Qwen/Qwen3.5-2B`가 최종 모델로 선정되었습니다. Whisper를 `tiny`에서 `small`로 변경한 추가 실험에서는 정확도 98.9%, RTF 1.0098이 측정되어 정확도 향상과 처리 지연 간의 트레이드오프를 확인했습니다.

> 위 수치는 발표 자료의 해당 Jetson 환경에서 측정한 결과입니다. 하드웨어 상태, 모델 파일, 양자화, 발화 속도와 주변 소음에 따라 달라질 수 있습니다.

## 종료 및 뒷정리

프로그램과 서버가 실행 중인 각 터미널에서 `Ctrl+C`를 누릅니다. 서버 터미널을 잃었다면 다음 명령으로 종료 상태를 확인합니다.

```bash
pkill -f "llama-server"
pgrep -af llama-server
```

`pgrep` 결과가 없으면 서버가 정상적으로 종료된 상태입니다.

## 문제 해결

### llama-server 연결 실패

- 터미널 A에서 서버가 실행 중인지 확인합니다.
- `curl http://127.0.0.1:8080/v1/models`가 응답하는지 확인합니다.
- 서버 포트와 `LLAMA_SERVER` 값이 같은지 확인합니다.

### 녹음 파일이 너무 짧다고 표시됨

- `arecord -l`로 마이크가 인식되는지 확인합니다.
- PulseAudio를 사용하지 않는 환경에서는 `AUDIO_DEV`를 실제 장치명으로 바꿉니다.
- 두 번째 Enter를 너무 빨리 누르지 않았는지 확인합니다.

### STT 모델을 불러오지 못함

- 가상환경에 `faster-whisper`가 설치되었는지 확인합니다.
- 오프라인으로 전환하기 전에 사용할 모델을 미리 내려받았는지 확인합니다.
- Jetson의 메모리가 부족하면 더 작은 모델 또는 더 낮은 양자화를 사용합니다.

## 보안 원칙

- 마이크 원본과 전사 결과를 외부 API 또는 클라우드 저장소로 전송하지 않습니다.
- `llama-server`는 기본적으로 루프백 주소(`127.0.0.1`)에만 바인딩합니다.
- 백업 파일은 Jetson 내부의 접근 통제된 경로에 저장하고 보존 기간을 정합니다.
- 실제 기업 회의에 적용할 때는 디스크 암호화, 사용자 권한 분리, 로그 마스킹 정책을 추가합니다.
