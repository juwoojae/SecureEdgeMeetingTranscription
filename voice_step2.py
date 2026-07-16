#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [실습 2] 실습1 + TTS(음성출력).  ★ [2단계 추가] 부분만 새로 붙였습니다.
#   TTS 엔진 전환:  TTS_ENGINE=edge (기본) | melo
import os, re, json, time, queue, threading, tempfile, subprocess, asyncio   # ★ [2단계 추가] re,queue,threading,asyncio
import urllib.request, urllib.error

LLAMA_SERVER = os.environ.get("LLAMA_SERVER", "http://127.0.0.1:8080")
ASR_MODEL    = os.environ.get("ASR_MODEL", "base")
AUDIO_DEV    = os.environ.get("AUDIO_DEV", "pulse")
N_PRED       = int(os.environ.get("N_PRED", "192"))
SYSTEM_HINT  = "너는 친절한 한국어 음성 비서야. 질문에 한국어로 한두 문장으로 간결하게 답해줘."
VA_TEXT      = os.environ.get("VA_TEXT")
TTS_ENGINE   = os.environ.get("TTS_ENGINE", "edge").lower()          # ★ [2단계 추가] edge | melo | gtts
EDGE_VOICE   = os.environ.get("EDGE_VOICE", "ko-KR-SunHiNeural")     # ★ [2단계 추가]

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

# ================= ★ [2단계 추가] 여기부터 TTS =================
def split_sentences(text):
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return []
    return [s.strip() for s in re.split(r"(?<=[.!?。…?!])\s+", text) if s.strip()]

_melo = None
def _melo_model():
    global _melo
    if _melo is None:
        import torch
        torch.set_num_threads(os.cpu_count() or 6)
        from melo.api import TTS
        print("[TTS] MeloTTS 한국어 모델 로딩...", flush=True)
        _melo = TTS(language="KR", device="cpu")
    return _melo

def synth(text, path_noext):
    if TTS_ENGINE == "melo":
        wav = path_noext + ".wav"
        m = _melo_model()
        m.tts_to_file(text, list(m.hps.data.spk2id.values())[0], wav, speed=1.0, quiet=True)
        return wav
    elif TTS_ENGINE == "edge":
        mp3 = path_noext + ".mp3"
        import edge_tts
        async def _run(): await edge_tts.Communicate(text, EDGE_VOICE).save(mp3)
        asyncio.run(_run())
        return mp3
    elif TTS_ENGINE == "gtts":
        mp3 = path_noext + ".mp3"
        from gtts import gTTS
        gTTS(text, lang="ko").save(mp3)
        return mp3
    raise SystemExit(f"알 수 없는 TTS_ENGINE: {TTS_ENGINE}")

def play(path):
    if path.endswith(".wav"):
        subprocess.run(["aplay", "-q", "-D", AUDIO_DEV, path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def speak_stream(sentences):
    if not sentences: return
    q = queue.Queue()
    def producer():
        for i, s in enumerate(sentences):
            try: q.put(synth(s, os.path.join(tempfile.gettempdir(), f"va_{i}")))
            except Exception as e: print(f"[TTS 오류] {e}")
        q.put(None)
    threading.Thread(target=producer, daemon=True).start()
    while True:
        f = q.get()
        if f is None: break
        play(f)
        try: os.remove(f)
        except OSError: pass
# ================= ★ [2단계 추가] 여기까지 TTS =================

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
    t2 = time.time()                              # ★ [2단계 추가] 아래 3줄: 음성 재생
    speak_stream(split_sentences(answer))         # ★ [2단계 추가]
    print(f"[TTS {TTS_ENGINE} {time.time()-t2:.1f}s] 재생 완료")   # ★ [2단계 추가]

def main():
    print(f"[실습2] STT -> LLM -> TTS({TTS_ENGINE}) | 서버 {LLAMA_SERVER} | ASR {ASR_MODEL}")
    if TTS_ENGINE == "melo":
        _melo_model()                             # ★ [2단계 추가] 미리 로딩
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