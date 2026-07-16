#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [실습 1] 내 목소리 -> STT(음성인식) -> LLM -> "텍스트" 답변 (TTS 없음)
import os, json, time, tempfile, subprocess
import urllib.request, urllib.error

LLAMA_SERVER = os.environ.get("LLAMA_SERVER", "http://127.0.0.1:8080")
ASR_MODEL    = os.environ.get("ASR_MODEL", "base")
AUDIO_DEV    = os.environ.get("AUDIO_DEV", "pulse")
N_PRED       = int(os.environ.get("N_PRED", "192"))
SYSTEM_HINT  = "너는 친절한 한국어 음성 비서야. 질문에 한국어로 한두 문장으로 간결하게 답해줘."
VA_TEXT      = os.environ.get("VA_TEXT")   # 있으면 녹음 대신 이 텍스트로 1회 실행(테스트용)

def ask_llm(user_text):
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM_HINT},
                     {"role": "user",   "content": user_text}],
        "temperature": 0.7, "max_tokens": N_PRED,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode("utf-8")
    req = urllib.request.Request(f"{LLAMA_SERVER}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=120))
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

def record(out):
    print("\n[Enter] 눌러 녹음 시작 -> 말하고 다시 [Enter] 눌러 종료")
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

def handle(text):
    print(f"[내가 말한 것] {text}")
    t = time.time()
    answer = ask_llm(text)
    print(f"[AI 답변 (LLM {time.time()-t:.1f}s)] {answer}")

def main():
    print(f"[실습1] STT -> LLM -> 텍스트 | 서버 {LLAMA_SERVER} | ASR {ASR_MODEL}")
    if VA_TEXT:
        handle(VA_TEXT); return
    while True:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav = f.name
        record(wav)
        if not os.path.exists(wav) or os.path.getsize(wav) < 8000:
            print("녹음이 너무 짧아요. 다시!"); continue
        print("-> 음성 인식 중...")
        text = transcribe(wav)
        try: os.remove(wav)
        except OSError: pass
        if not text:
            print("인식된 게 없어요. 다시!"); continue
        handle(text)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n종료합니다.")