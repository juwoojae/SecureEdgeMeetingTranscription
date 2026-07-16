#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, wave, json, time, tempfile, subprocess, contextlib
import urllib.request, urllib.error

LLAMA_SERVER = os.environ.get("LLAMA_SERVER", "http://127.0.0.1:8080")
ASR_MODEL    = os.environ.get("ASR_MODEL", "tiny")   # ★ 사용
AUDIO_DEV    = os.environ.get("AUDIO_DEV", "pulse")
N_PRED       = int(os.environ.get("N_PRED", "1024")) # 회의록 전체를 뱉어야 하므로 넉넉히

SYSTEM_HINT = (
    "너는 한국어 회의록 교정 전문가야. 아래 텍스트는 회의 음성을 STT로 자동 전사한 결과인데, "
    "음성 인식 오류 때문에 잘못 인식된 단어나 어색한 표현, 오탈자가 섞여 있어. "
    "원래 발화 의도를 추정해서 문법·맞춤법·잘못 인식된 단어를 자연스럽고 올바른 한국어로 교정한 "
    "전체 회의록을 출력해줘. 없는 내용을 새로 지어내지 말고, 있는 문장만 다듬어. "
    "설명이나 머리말 없이 교정된 회의록 본문만 출력해."
)

def ask_llm(user_text):
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM_HINT},
                     {"role": "user",   "content": user_text}],
        "temperature": 0.3, "max_tokens": N_PRED,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode("utf-8")
    req = urllib.request.Request(f"{LLAMA_SERVER}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=180))
    except urllib.error.URLError:
        print("[오류] llama-server에 연결 실패. 터미널 A에서 서버를 먼저 켜세요.")
        raise SystemExit(1)
    return d["choices"][0]["message"]["content"].strip()

_asr = None
def transcribe(wav):
    global _asr
    if _asr is None:
        from faster_whisper import WhisperModel
        _asr = WhisperModel(ASR_MODEL, device="cpu", compute_type="int8")
    segs, _ = _asr.transcribe(wav, language="ko", vad_filter=True)
    return "".join(s.text for s in segs).strip()

def wav_seconds(path):
    with contextlib.closing(wave.open(path, "rb")) as w:
        return w.getnframes() / float(w.getframerate())

def record(out):
    print("\n[Enter] 눌러 녹음 시작 -> 대본을 낭독하고 다시 [Enter] 눌러 종료")
    input("준비되면 Enter... ")
    p = subprocess.Popen(["arecord", "-D", AUDIO_DEV, "-f", "S16_LE",
                          "-r", "16000", "-c", "1", out],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        input("* 녹음 중... 끝나면 Enter... ")
    finally:
        p.terminate()
        try: p.wait(timeout=2)
        except subprocess.TimeoutExpired: p.kill()

def main():
    print(f"[회의 전사 POC] STT -> LLM 교정 | 서버 {LLAMA_SERVER}")
    while True:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav = f.name
        record(wav)
        if not os.path.exists(wav) or os.path.getsize(wav) < 8000:
            print("녹음이 너무 짧아요. 다시!"); continue

        in_sec = wav_seconds(wav)          # 1) 입력 음성 길이

        t0 = time.time()                    # -- 총 처리 시간 측정 시작 --
        print("-> 음성 인식 중...")
        raw = transcribe(wav)
        try: os.remove(wav)
        except OSError: pass
        if not raw:
            print("인식된 게 없어요. 다시!"); continue

        print("\n===== STT 원본 =====")
        print(raw)

        print("\n-> LLM이 회의록 교정 중...")
        fixed = ask_llm(raw)
        total_sec = time.time() - t0        # 2) 총 처리 시간 (입력 후 출력까지)

        print("\n===== LLM 교정 회의록 =====")
        print(fixed)

        # -- 측정값 표 --
        print("\n+" + "-" * 44 + "+")
        print(f"| 1) 입력 음성 길이       : {in_sec:7.2f} s")
        print(f"| 2) 입력 후 출력 시간    : {total_sec:7.2f} s")
        print("+" + "-" * 44 + "+")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n종료합니다.")