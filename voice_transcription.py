#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import wave
import json
import time
import signal
import shutil
import tempfile
import subprocess
import contextlib
import urllib.request
import urllib.error

from datetime import datetime
from pathlib import Path


def env_bool(name, default=False):
    """환경변수의 true/false 값을 bool로 변환한다."""

    default_value = "1" if default else "0"

    return os.environ.get(name, default_value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on"
    }


# =========================================================
# llama-server 설정
# =========================================================

LLAMA_SERVER = os.environ.get(
    "LLAMA_SERVER",
    "http://127.0.0.1:8080"
)

# 저장 파일에 표시할 LLM 이름
LLM_MODEL_NAME = os.environ.get(
    "LLM_MODEL_NAME",
    "llama-server 실행 모델"
)

# LLM의 회의록 최대 출력 토큰
N_PRED = int(
    os.environ.get("N_PRED", "1024")
)

# 한 줄 요약 최대 출력 토큰
SUMMARY_N_PRED = int(
    os.environ.get("SUMMARY_N_PRED", "128")
)


# =========================================================
# STT 설정
# =========================================================

# 정확도를 높이기 위해 기본값을 tiny가 아닌 small로 설정
# 이미 다운로드한 base를 사용하려면 ASR_MODEL=base로 실행
ASR_MODEL = os.environ.get(
    "ASR_MODEL",
    "small"
)

ASR_DEVICE = os.environ.get(
    "ASR_DEVICE",
    "cpu"
)

ASR_COMPUTE_TYPE = os.environ.get(
    "ASR_COMPUTE_TYPE",
    "int8"
)

ASR_BEAM_SIZE = int(
    os.environ.get("ASR_BEAM_SIZE", "5")
)

# Whisper가 반도체 용어를 더 잘 인식하도록 제공하는 사전 문맥
ASR_INITIAL_PROMPT = os.environ.get(
    "ASR_INITIAL_PROMPT",
    (
        "반도체 회사의 수율 관리 회의입니다. "
        "주요 용어는 공정팀, 품질팀, D2 라인, 평균 수율, "
        "전주 대비, 퍼센트포인트, 식각 공정, 과식각, 식각 시간, "
        "웨이퍼, 가장자리 다이, 불량, 재검증, 로트, 파티클, "
        "클린룸, 필터 교체 주기, CMP 장비, 배기 라인입니다."
    )
)


# =========================================================
# 녹음 설정
# =========================================================

AUDIO_DEV = os.environ.get(
    "AUDIO_DEV",
    "pulse"
)


# =========================================================
# 저장 설정
# =========================================================

SAVE_DIR = Path(
    os.environ.get("MEET_SAVE_DIR", "~/meet")
).expanduser()

# 원본 WAV까지 백업할지 여부
SAVE_AUDIO = env_bool(
    "SAVE_AUDIO",
    True
)


# =========================================================
# TTS 설정
# =========================================================

# 기본값은 비활성화
ENABLE_TTS = env_bool(
    "ENABLE_TTS",
    False
)

TTS_DEVICE = os.environ.get(
    "TTS_DEVICE",
    "cpu"
)

TTS_SPEED = float(
    os.environ.get("TTS_SPEED", "1.0")
)


# =========================================================
# LLM 프롬프트
# =========================================================

SYSTEM_HINT = (
    "너는 한국어 회의록 교정 전문가야. "
    "아래 텍스트는 회의 음성을 STT로 자동 전사한 결과인데, "
    "음성 인식 오류로 잘못 인식된 단어, 어색한 표현, 오탈자가 섞여 있어. "
    "원래 발화 의도를 바탕으로 문법, 맞춤법 및 잘못 인식된 단어를 "
    "자연스럽고 올바른 한국어로 교정한 전체 회의록을 출력해줘. "
    "회의록에 없는 내용을 새로 만들거나 기존 내용을 삭제하지 마. "
    "숫자, 날짜, 시간, 인명, 부서명, 장비명 및 핵심 수치를 임의로 변경하지 마. "
    "설명, 분석, 머리말, 제목 없이 교정된 회의록 본문만 출력해."
)


SUMMARY_HINT = (
    "너는 한국어 회의 내용을 요약하는 전문가야. "
    "아래 회의록에서 핵심 보고 내용, 문제 원인, 조치 사항과 결정 사항을 추출하여 "
    "반드시 한 문장으로만 요약해줘. "
    "회의록에 존재하지 않는 내용을 추가하거나 수치와 날짜를 변경하지 마. "
    "제목, 머리말, 글머리표 및 설명 없이 요약 문장만 출력해."
)


# =========================================================
# 공통 유틸리티
# =========================================================

def safe_remove(path):
    """파일이 존재하면 안전하게 삭제한다."""

    try:
        os.remove(path)
    except OSError:
        pass


def request_llm(system_prompt, user_text, max_tokens, temperature=0.3):
    """llama-server의 Chat Completions API를 호출한다."""

    body = json.dumps(
        {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": False
            }
        },
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{LLAMA_SERVER}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=180
        ) as response:
            data = json.load(response)

    except urllib.error.URLError as error:
        print("\n[오류] llama-server에 연결하지 못했습니다.")
        print("터미널 A에서 llama-server를 먼저 실행하세요.")
        print(f"상세 오류: {error}")
        raise RuntimeError("llama-server 연결 실패") from error

    try:
        return (
            data["choices"][0]["message"]["content"]
            .strip()
        )

    except (KeyError, IndexError, TypeError) as error:
        print("\n[오류] llama-server 응답 형식이 올바르지 않습니다.")
        print(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )
        )

        raise RuntimeError(
            "LLM 응답 파싱 실패"
        ) from error


def ask_llm(user_text):
    """STT 원문을 교정된 회의록으로 변환한다."""

    return request_llm(
        system_prompt=SYSTEM_HINT,
        user_text=user_text,
        max_tokens=N_PRED,
        temperature=0.2
    )


def summarize_minutes(fixed_text):
    """교정된 회의록을 한 문장으로 요약한다."""

    summary = request_llm(
        system_prompt=SUMMARY_HINT,
        user_text=fixed_text,
        max_tokens=SUMMARY_N_PRED,
        temperature=0.1
    )

    # 모델이 여러 줄을 출력하더라도 한 줄로 합친다.
    return " ".join(
        summary.splitlines()
    ).strip()


# =========================================================
# STT
# =========================================================

_asr = None


def load_asr():
    """faster-whisper 모델을 한 번만 메모리에 적재한다."""

    global _asr

    if _asr is not None:
        return _asr

    print(
        f"[STT 모델 로딩] "
        f"model={ASR_MODEL}, "
        f"device={ASR_DEVICE}, "
        f"compute_type={ASR_COMPUTE_TYPE}"
    )

    from faster_whisper import WhisperModel

    _asr = WhisperModel(
        ASR_MODEL,
        device=ASR_DEVICE,
        compute_type=ASR_COMPUTE_TYPE
    )

    print("[STT 모델 로딩 완료]")

    return _asr


def transcribe(wav_path):
    """faster-whisper로 한국어 음성을 전사한다."""

    model = load_asr()

    segments, _ = model.transcribe(
        wav_path,
        language="ko",
        beam_size=ASR_BEAM_SIZE,
        temperature=0.0,
        vad_filter=True,
        condition_on_previous_text=True,
        initial_prompt=ASR_INITIAL_PROMPT
    )

    texts = []

    for segment in segments:
        text = segment.text.strip()

        if text:
            texts.append(text)

    # 문장 사이가 붙지 않도록 공백으로 연결한다.
    return " ".join(texts).strip()


# =========================================================
# TTS
# =========================================================

_tts = None


def synthesize_summary(summary, output_path):
    """
    AI 한 줄 요약을 MeloTTS로 음성 파일로 저장한다.
    ENABLE_TTS=1일 때만 실행한다.
    """

    global _tts

    if not ENABLE_TTS:
        return None

    try:
        if _tts is None:
            print(
                f"[TTS 모델 로딩] "
                f"language=KR, device={TTS_DEVICE}"
            )

            from melo.api import TTS

            _tts = TTS(
                language="KR",
                device=TTS_DEVICE
            )

            print("[TTS 모델 로딩 완료]")

        speaker_ids = _tts.hps.data.spk2id

        # 일반적으로 한국어 화자 키는 KR이지만,
        # 없을 경우 첫 번째 화자를 사용한다.
        speaker_id = speaker_ids.get("KR")

        if speaker_id is None:
            speaker_id = next(
                iter(speaker_ids.values())
            )

        _tts.tts_to_file(
            summary,
            speaker_id,
            str(output_path),
            speed=TTS_SPEED
        )

        return output_path

    except Exception as error:
        print(f"[경고] TTS 생성에 실패했습니다: {error}")
        return None


# =========================================================
# WAV 녹음 및 길이 계산
# =========================================================

def wav_seconds(path):
    """WAV 파일의 재생 길이를 초 단위로 반환한다."""

    with contextlib.closing(
        wave.open(path, "rb")
    ) as wav_file:
        return (
            wav_file.getnframes()
            / float(wav_file.getframerate())
        )


def record(output_path):
    """Enter 입력을 기준으로 녹음을 시작하고 종료한다."""

    print(
        "\n[Enter]를 눌러 녹음을 시작하고, "
        "대본 낭독 후 다시 [Enter]를 눌러 종료합니다."
    )

    input("준비되면 Enter... ")

    try:
        process = subprocess.Popen(
            [
                "arecord",
                "-D", AUDIO_DEV,
                "-f", "S16_LE",
                "-r", "16000",
                "-c", "1",
                output_path
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except FileNotFoundError as error:
        print("[오류] arecord 명령어를 찾지 못했습니다.")
        print("sudo apt install alsa-utils 명령으로 설치하세요.")
        raise RuntimeError(
            "arecord 실행 실패"
        ) from error

    try:
        input("* 녹음 중... 끝나면 Enter... ")

    finally:
        # SIGINT를 보내야 WAV 헤더가 정상적으로 마무리된다.
        process.send_signal(signal.SIGINT)

        try:
            process.wait(timeout=3)

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


# =========================================================
# 결과 파일 저장
# =========================================================

def save_result(
    raw,
    fixed,
    summary,
    wav_path,
    timestamp,
    in_sec,
    stt_sec,
    correction_sec,
    assignment_total_sec,
    assignment_rtf,
    summary_sec,
    tts_sec,
    enhanced_total_sec,
    tts_output_path
):
    """회의 처리 결과를 날짜·시간별 파일로 저장한다."""

    SAVE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    now = datetime.now()

    text_output_path = (
        SAVE_DIR / f"bak_{timestamp}.txt"
    )

    audio_output_path = None

    if SAVE_AUDIO:
        audio_output_path = (
            SAVE_DIR / f"audio_{timestamp}.wav"
        )

        try:
            shutil.copy2(
                wav_path,
                audio_output_path
            )

        except OSError as error:
            print(
                f"[경고] 원본 녹음 파일 백업 실패: {error}"
            )

            audio_output_path = None

    content = (
        "===== 실행 정보 =====\n"
        f"저장 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"STT 모델: {ASR_MODEL}\n"
        f"STT 장치: {ASR_DEVICE}\n"
        f"STT 연산 형식: {ASR_COMPUTE_TYPE}\n"
        f"STT Beam Size: {ASR_BEAM_SIZE}\n"
        f"LLM 모델: {LLM_MODEL_NAME}\n"
        "\n"
        "===== 과제 성능 측정 =====\n"
        f"입력 음성 길이: {in_sec:.2f}초\n"
        f"STT 처리 시간: {stt_sec:.2f}초\n"
        f"LLM 교정 시간: {correction_sec:.2f}초\n"
        f"입력 후 교정 출력 시간: {assignment_total_sec:.2f}초\n"
        f"과제용 RTF: {assignment_rtf:.4f}\n"
        "\n"
        "===== 추가 기능 처리 시간 =====\n"
        f"한 줄 요약 시간: {summary_sec:.2f}초\n"
        f"TTS 처리 시간: {tts_sec:.2f}초\n"
        f"전체 고도화 처리 시간: {enhanced_total_sec:.2f}초\n"
        "\n"
        "===== AI 한 줄 요약 =====\n"
        f"{summary}\n"
        "\n"
        "===== STT 원본 =====\n"
        f"{raw}\n"
        "\n"
        "===== LLM 교정 회의록 =====\n"
        f"{fixed}\n"
        "\n"
        "===== 백업 파일 =====\n"
        f"원본 음성: "
        f"{audio_output_path if audio_output_path else '저장 안 함'}\n"
        f"요약 음성: "
        f"{tts_output_path if tts_output_path else '생성 안 함'}\n"
    )

    try:
        with text_output_path.open(
            mode="w",
            encoding="utf-8"
        ) as file:
            file.write(content)

    except OSError as error:
        print(
            f"[오류] 결과 파일을 저장하지 못했습니다: {error}"
        )

        return None, audio_output_path

    return text_output_path, audio_output_path


# =========================================================
# 한 회의 처리
# =========================================================

def process_one_meeting():
    """녹음 한 건을 전사, 교정, 요약 및 백업한다."""

    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False
    ) as temp_file:
        wav_path = temp_file.name

    try:
        record(wav_path)

        if (
            not os.path.exists(wav_path)
            or os.path.getsize(wav_path) < 8000
        ):
            print("녹음이 너무 짧습니다. 다시 녹음하세요.")
            return

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        SAVE_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        # 입력 음성 길이
        in_sec = wav_seconds(wav_path)

        # ---------------------------------------------
        # 과제용 처리 시간 측정 시작
        # STT 시작부터 LLM 교정 완료까지 측정
        # ---------------------------------------------
        process_start = time.perf_counter()

        print("\n-> 음성 인식 중...")

        stt_start = time.perf_counter()

        raw = transcribe(wav_path)

        stt_sec = (
            time.perf_counter() - stt_start
        )

        if not raw:
            print("인식된 음성이 없습니다. 다시 녹음하세요.")
            return

        print("\n===== STT 원본 =====")
        print(raw)

        print("\n-> LLM이 회의록 교정 중...")

        correction_start = time.perf_counter()

        fixed = ask_llm(raw)

        correction_sec = (
            time.perf_counter() - correction_start
        )

        # 과제의 원래 출력인 교정 회의록 생성까지 측정
        assignment_total_sec = (
            time.perf_counter() - process_start
        )

        assignment_rtf = (
            assignment_total_sec / in_sec
            if in_sec > 0
            else 0.0
        )

        print("\n===== LLM 교정 회의록 =====")
        print(fixed)

        # ---------------------------------------------
        # 추가 고도화 기능
        # ---------------------------------------------

        print("\n-> AI가 회의 내용을 한 줄로 요약 중...")

        summary_start = time.perf_counter()

        summary = summarize_minutes(fixed)

        summary_sec = (
            time.perf_counter() - summary_start
        )

        print("\n===== AI 한 줄 요약 =====")
        print(summary)

        # TTS는 환경변수로 켰을 때만 실행
        tts_output_path = None
        tts_sec = 0.0

        if ENABLE_TTS:
            print("\n-> 한 줄 요약 음성 생성 중...")

            tts_start = time.perf_counter()

            candidate_tts_path = (
                SAVE_DIR / f"summary_{timestamp}.wav"
            )

            tts_output_path = synthesize_summary(
                summary,
                candidate_tts_path
            )

            tts_sec = (
                time.perf_counter() - tts_start
            )

        enhanced_total_sec = (
            time.perf_counter() - process_start
        )

        print("\n+" + "-" * 56 + "+")
        print(
            f"| 입력 음성 길이             : "
            f"{in_sec:9.2f} s"
        )
        print(
            f"| STT 처리 시간              : "
            f"{stt_sec:9.2f} s"
        )
        print(
            f"| LLM 교정 시간              : "
            f"{correction_sec:9.2f} s"
        )
        print(
            f"| 입력 후 교정 출력 시간     : "
            f"{assignment_total_sec:9.2f} s"
        )
        print(
            f"| 과제용 RTF                 : "
            f"{assignment_rtf:9.4f}"
        )
        print(
            f"| 한 줄 요약 시간            : "
            f"{summary_sec:9.2f} s"
        )

        if ENABLE_TTS:
            print(
                f"| TTS 처리 시간              : "
                f"{tts_sec:9.2f} s"
            )

        print(
            f"| 전체 고도화 처리 시간      : "
            f"{enhanced_total_sec:9.2f} s"
        )
        print("+" + "-" * 56 + "+")

        text_path, audio_path = save_result(
            raw=raw,
            fixed=fixed,
            summary=summary,
            wav_path=wav_path,
            timestamp=timestamp,
            in_sec=in_sec,
            stt_sec=stt_sec,
            correction_sec=correction_sec,
            assignment_total_sec=assignment_total_sec,
            assignment_rtf=assignment_rtf,
            summary_sec=summary_sec,
            tts_sec=tts_sec,
            enhanced_total_sec=enhanced_total_sec,
            tts_output_path=tts_output_path
        )

        if text_path is not None:
            print(f"\n[텍스트 저장 완료] {text_path}")

        if audio_path is not None:
            print(f"[원본 음성 저장 완료] {audio_path}")

        if tts_output_path is not None:
            print(f"[요약 음성 저장 완료] {tts_output_path}")

    finally:
        safe_remove(wav_path)


# =========================================================
# 프로그램 시작
# =========================================================

def main():
    print("=" * 68)
    print("기업 보안 환경용 온디바이스 회의 전사 PoC")
    print("=" * 68)

    print(f"LLM 서버        : {LLAMA_SERVER}")
    print(f"STT 모델        : {ASR_MODEL}")
    print(f"STT 실행 장치   : {ASR_DEVICE}")
    print(f"STT 연산 형식   : {ASR_COMPUTE_TYPE}")
    print(f"STT Beam Size   : {ASR_BEAM_SIZE}")
    print(f"저장 경로       : {SAVE_DIR}")
    print(f"원본 음성 백업  : {SAVE_AUDIO}")
    print(f"TTS 사용        : {ENABLE_TTS}")

    while True:
        process_one_meeting()

        command = input(
            "\n다시 녹음하려면 Enter, 종료하려면 q를 입력하세요: "
        ).strip().lower()

        if command == "q":
            break

    print("\n프로그램을 종료합니다.")


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\n사용자 입력으로 종료합니다.")

    except Exception as error:
        print(f"\n[실행 오류] {error}")