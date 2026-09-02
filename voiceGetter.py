import os
import sys
import subprocess
import shutil
import torch

# --- MONKEY-PATCH: Provide missing helper to satisfy Coqui TTS on modern transformers ---
import transformers.pytorch_utils
if not hasattr(transformers.pytorch_utils, "isin_mps_friendly"):
    def isin_mps_friendly(elements, test_elements):
        return torch.isin(elements, test_elements)
    transformers.pytorch_utils.isin_mps_friendly = isin_mps_friendly
# ---------------------------------------------------------------------------------------

import pysrt
from pydub import AudioSegment

# Apple Silicon Homebrew binary paths fallback
if os.path.exists("/opt/homebrew/bin/ffmpeg"):
    AudioSegment.converter = "/opt/homebrew/bin/ffmpeg"
    AudioSegment.ffprobe = "/opt/homebrew/bin/ffprobe"
    FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
else:
    FFMPEG_BIN = "ffmpeg"

import whisper
from transformers import AutoModelForCausalLM, AutoTokenizer
from TTS.api import TTS

# Configuration & Paths
INPUT_VIDEO = "input_video.mp4"
RAW_AUDIO = "output_audio.wav"
ARABIC_SRT = "arabic_subtitles.srt"
TURKISH_SRT = "turkish_subtitles.srt"
DUBBED_VOCALS = "dubbed_vocals.wav"
FINAL_MIX_AUDIO = "final_mix_audio.wav"
FINAL_VIDEO = "output_dubbed_video.mp4"
DEMUCS_OUT_DIR = "demucs_separated"

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Using compute device: {DEVICE}")


# --------------------------------------------------------------------
# Step 1: Extract Audio from Video using FFmpeg
# --------------------------------------------------------------------
def extract_audio():
    print("\n--- Step 1: Extracting clean WAV from video ---")
    if not os.path.exists(INPUT_VIDEO):
        print(f"Error: Input video file '{INPUT_VIDEO}' not found.")
        sys.exit(1)

    extract_audio_cmd = [
        FFMPEG_BIN,
        "-i", INPUT_VIDEO,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        RAW_AUDIO,
        "-y"
    ]
    subprocess.run(extract_audio_cmd, check=True)
    print(f"Audio extracted successfully to: {RAW_AUDIO}")


# --------------------------------------------------------------------
# Step 2: Separate Vocals and Background with Demucs
# --------------------------------------------------------------------
def separate_audio():
    print("\n--- Step 2: Separating Vocals and Background with Demucs ---")
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", "htdemucs",
        "--two-stems", "vocals",
        "-o", DEMUCS_OUT_DIR,
        RAW_AUDIO
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running Demucs: {e}")
        print("Ensure demucs is installed: pip install demucs")
        sys.exit(1)

    # Demucs saves to: demucs_separated/htdemucs/output_audio/vocals.wav
    stem_folder = os.path.join(DEMUCS_OUT_DIR, "htdemucs", os.path.splitext(RAW_AUDIO)[0])
    vocals_path = os.path.join(stem_folder, "vocals.wav")
    no_vocals_path = os.path.join(stem_folder, "no_vocals.wav")

    if not os.path.exists(vocals_path) or not os.path.exists(no_vocals_path):
        print(f"Error: Demucs stems not found in {stem_folder}")
        sys.exit(1)

    print(f"Vocals separated: {vocals_path}")
    print(f"Background audio separated: {no_vocals_path}")
    return vocals_path, no_vocals_path


# --------------------------------------------------------------------
# Step 3: Transcribe Arabic Speech to Subtitles with Whisper
# --------------------------------------------------------------------
def transcribe_arabic(vocals_path):
    print("\n--- Step 3: Transcribing Arabic vocals with Whisper ---")
    model = whisper.load_model("medium", device="cpu")
    result = model.transcribe(vocals_path, language="ar", task="transcribe")

    subs = pysrt.SubRipFile()
    for i, seg in enumerate(result["segments"], start=1):
        start = pysrt.SubRipTime(milliseconds=int(seg["start"] * 1000))
        end = pysrt.SubRipTime(milliseconds=int(seg["end"] * 1000))
        item = pysrt.SubRipItem(index=i, start=start, end=end, text=seg["text"].strip())
        subs.append(item)

    subs.save(ARABIC_SRT, encoding="utf-8")
    print(f"Arabic subtitles saved to: {ARABIC_SRT}")
    return subs


# --------------------------------------------------------------------
# Step 4: Translate Arabic Subtitles to Turkish with Qwen2.5
# --------------------------------------------------------------------
def translate_to_turkish(subs):
    print("\n--- Step 4: Translating subtitles with Qwen2.5-7B ---")
    model_name = "Qwen/Qwen2.5-7B-Instruct"

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        device_map="auto"
    )

    translated_subs = pysrt.SubRipFile()

    for item in subs:
        arabic_text = item.text.strip()
        if not arabic_text:
            continue

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional film dubbing translator. Translate the Arabic "
                    "sentence directly into natural Turkish. Output ONLY the Turkish translation."
                )
            },
            {"role": "user", "content": arabic_text}
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([prompt], return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=128,
                temperature=0.2,
                top_p=0.9
            )

        gen_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(inputs.input_ids, outputs)
        ]
        turkish_text = tokenizer.batch_decode(gen_ids, skip_special_tokens=True)[0].strip()
        print(f"AR: {arabic_text} -> TR: {turkish_text}")

        tr_item = pysrt.SubRipItem(
            index=item.index,
            start=item.start,
            end=item.end,
            text=turkish_text
        )
        translated_subs.append(tr_item)

    # Free Qwen model memory before loading XTTS
    del model
    del tokenizer
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()

    translated_subs.save(TURKISH_SRT, encoding="utf-8")
    print(f"Turkish subtitles saved to: {TURKISH_SRT}")
    return translated_subs


# --------------------------------------------------------------------
# Step 5: Synthesize Turkish Dub with XTTS-v2 and Clone Voice
# --------------------------------------------------------------------
def dub_with_cloned_voice(translated_subs, vocals_path):
    print("\n--- Step 5: Synthesizing cloned Turkish speech via XTTS-v2 ---")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)

    orig_vocals = AudioSegment.from_wav(vocals_path)
    final_vocals_canvas = AudioSegment.silent(duration=len(orig_vocals))

    # Grab the first 10-12 seconds of clean vocals as reference sample
    voice_sample_path = "voice_sample.wav"
    sample_len = min(12000, len(orig_vocals))
    orig_vocals[0:sample_len].export(voice_sample_path, format="wav")

    os.makedirs("temp_segments", exist_ok=True)

    for item in translated_subs:
        start_ms = (item.start.hours * 3600 + item.start.minutes * 60 + item.start.seconds) * 1000 + item.start.milliseconds
        end_ms = (item.end.hours * 3600 + item.end.minutes * 60 + item.end.seconds) * 1000 + item.end.milliseconds
        target_slot_len = end_ms - start_ms

        line = item.text.strip()
        if not line:
            continue

        temp_seg_file = f"temp_segments/segment_{item.index}.wav"
        tts.tts_to_file(
            text=line,
            file_path=temp_seg_file,
            speaker_wav=voice_sample_path,
            language="tr"
        )

        synth_seg = AudioSegment.from_wav(temp_seg_file)

        # Fit speech within visual duration if needed
        if len(synth_seg) > target_slot_len and target_slot_len > 0:
            speed_ratio = min(len(synth_seg) / target_slot_len, 1.3)
            synth_seg = synth_seg.speedup(playback_speed=speed_ratio)

        final_vocals_canvas = final_vocals_canvas.overlay(synth_seg, position=start_ms)

    final_vocals_canvas.export(DUBBED_VOCALS, format="wav")
    print(f"Dubbed vocals rendered to: {DUBBED_VOCALS}")


# --------------------------------------------------------------------
# Step 6: Mix Dubbed Vocals with Original Background Track & Remux Video
# --------------------------------------------------------------------
def mix_and_finalize_video(no_vocals_path):
    print("\n--- Step 6: Mixing background audio and remuxing final video ---")
    background = AudioSegment.from_wav(no_vocals_path)
    dubbed_vocals = AudioSegment.from_wav(DUBBED_VOCALS)

    # Combine new Turkish speech over original background music/SFX
    final_mix = background.overlay(dubbed_vocals)
    final_mix.export(FINAL_MIX_AUDIO, format="wav")

    # Merge audio back into original video
    remux_cmd = [
        FFMPEG_BIN, "-y",
        "-i", INPUT_VIDEO,
        "-i", FINAL_MIX_AUDIO,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        FINAL_VIDEO
    ]
    subprocess.run(remux_cmd, check=True)
    print(f"\nPipeline finished! Final output video: {FINAL_VIDEO}")


# --------------------------------------------------------------------
# Main Execution Pipeline
# --------------------------------------------------------------------
def main():
    extract_audio()
    vocals_path, no_vocals_path = separate_audio()
    arabic_subs = transcribe_arabic(vocals_path)
    turkish_subs = translate_to_turkish(arabic_subs)
    dub_with_cloned_voice(turkish_subs, vocals_path)
    mix_and_finalize_video(no_vocals_path)


if __name__ == "__main__":
    main()