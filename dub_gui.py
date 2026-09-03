# dub_gui.py

import os
import sys
import threading
import subprocess
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pysrt
import dub_pipeline

LANG_MAP = {
    "Turkish": "tr",
    "Hindi": "hi",
    "Arabic": "ar",
    "Russian": "ru",
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Polish": "pl",
    "Dutch": "nl",
    "Czech": "cs",
    "Chinese": "zh-cn",
    "Korean": "ko",
    "Hungarian": "hu"
}

FFPLAY_BIN = "/opt/homebrew/bin/ffplay" if os.path.exists("/opt/homebrew/bin/ffplay") else shutil.which("ffplay")


class StudioApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Local Video Dubbing & Translation Studio")
        self.geometry("1240x860")
        self.minsize(1050, 720)

        # Global in-memory caches
        self.src_subs = pysrt.SubRipFile()
        self.tgt_subs = pysrt.SubRipFile()
        self.current_preview_video = None
        self.ffplay_proc = None

        self.setup_ui()

    def setup_ui(self):
        # Top Notebook (Tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.tab1 = ttk.Frame(self.notebook)
        self.tab2 = ttk.Frame(self.notebook)
        self.tab3 = ttk.Frame(self.notebook)

        self.notebook.add(self.tab1, text="  1. Subtitle & Video Editor  ")
        self.notebook.add(self.tab2, text="  2. XTTS Voice Dubbing  ")
        self.notebook.add(self.tab3, text="  3. Whisper & Qwen Studio  ")

        self.build_tab1_editor()
        self.build_tab2_xtts()
        self.build_tab3_whisper_qwen()

        # Global Bottom Activity Log
        log_frame = ttk.LabelFrame(self, text=" System Activity Log ", padding=8)
        log_frame.pack(fill="x", padx=10, pady=6)
        self.log_text = tk.Text(log_frame, height=5, state="disabled", bg="#1E1E1E", fg="#D4D4D4", font=("Menlo", 10))
        self.log_text.pack(fill="x")

    def log(self, message):
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _append)

    # =========================================================================
    # TAB 1: 3-WAY SPLIT SUBTITLE & VIDEO STUDIO
    # =========================================================================
    def build_tab1_editor(self):
        top_bar = ttk.Frame(self.tab1, padding=8)
        top_bar.pack(fill="x")

        ttk.Button(top_bar, text="Load Video", command=self.t1_load_video).pack(side="left", padx=4)
        ttk.Button(top_bar, text="Load Source SRT", command=self.t1_load_src_srt).pack(side="left", padx=4)
        ttk.Button(top_bar, text="Load Target SRT", command=self.t1_load_tgt_srt).pack(side="left", padx=4)
        ttk.Button(top_bar, text="Save Both SRTs", command=self.t1_save_both_srts).pack(side="left", padx=12)

        self.t1_status_lbl = ttk.Label(top_bar, text="No video or subtitles loaded.")
        self.t1_status_lbl.pack(side="right", padx=10)

        # 3-Way Paned Horizontal Window
        paned = ttk.PanedWindow(self.tab1, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        # Column 1: Source Transcript
        left_frame = ttk.LabelFrame(paned, text=" Source Transcript ", padding=6)
        paned.add(left_frame, weight=3)

        self.src_listbox = tk.Listbox(left_frame, font=("Menlo", 11), selectmode="browse")
        src_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.src_listbox.yview)
        self.src_listbox.configure(yscrollcommand=src_scroll.set)
        self.src_listbox.pack(side="left", fill="both", expand=True)
        src_scroll.pack(side="right", fill="y")
        self.src_listbox.bind("<<ListboxSelect>>", lambda e: self.t1_on_select("src"))
        self.src_listbox.bind("<Double-Button-1>", lambda e: self.t1_play_selected_segment())

        # Column 2: Target Translation
        mid_frame = ttk.LabelFrame(paned, text=" Target Translation (Editable) ", padding=6)
        paned.add(mid_frame, weight=3)

        self.tgt_listbox = tk.Listbox(mid_frame, font=("Menlo", 11), selectmode="browse")
        tgt_scroll = ttk.Scrollbar(mid_frame, orient="vertical", command=self.tgt_listbox.yview)
        self.tgt_listbox.configure(yscrollcommand=tgt_scroll.set)
        self.tgt_listbox.pack(side="left", fill="both", expand=True)
        tgt_scroll.pack(side="right", fill="y")
        self.tgt_listbox.bind("<<ListboxSelect>>", lambda e: self.t1_on_select("tgt"))
        self.tgt_listbox.bind("<Double-Button-1>", lambda e: self.t1_play_selected_segment())

        # Column 3: Video Player & Inspector
        right_frame = ttk.LabelFrame(paned, text=" Video Preview & Segment Controls ", padding=6)
        paned.add(right_frame, weight=2)

        self.t1_video_info = ttk.Label(right_frame, text="No video selected", wraplength=220)
        self.t1_video_info.pack(pady=10)

        ttk.Button(right_frame, text="▶ Play Entire Video", command=self.t1_play_full_video).pack(fill="x", padx=10, pady=4)
        ttk.Button(right_frame, text="⚡ Play Selected Segment", command=self.t1_play_selected_segment).pack(fill="x", padx=10, pady=4)
        ttk.Button(right_frame, text="⏹ Stop Player", command=self.t1_stop_player).pack(fill="x", padx=10, pady=4)

        ttk.Separator(right_frame, orient="horizontal").pack(fill="x", pady=15)
        self.t1_time_lbl = ttk.Label(right_frame, text="Selected Time: --:-- --> --:--")
        self.t1_time_lbl.pack(pady=4)

        # Bottom Edit Bar for Tab 1
        edit_card = ttk.Frame(self.tab1, padding=8)
        edit_card.pack(fill="x", padx=8, pady=4)

        ttk.Label(edit_card, text="Source Line:").grid(row=0, column=0, sticky="w")
        self.t1_edit_src_entry = ttk.Entry(edit_card, width=95)
        self.t1_edit_src_entry.grid(row=0, column=1, padx=6, pady=2, sticky="ew")

        ttk.Label(edit_card, text="Target Line:").grid(row=1, column=0, sticky="w")
        self.t1_edit_tgt_entry = ttk.Entry(edit_card, width=95)
        self.t1_edit_tgt_entry.grid(row=1, column=1, padx=6, pady=2, sticky="ew")

        ttk.Button(edit_card, text="Update Selected Line", command=self.t1_commit_edit).grid(row=0, column=2, rowspan=2, padx=10)
        edit_card.columnconfigure(1, weight=1)

    def t1_load_video(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.mov *.mkv *.avi")])
        if file_path:
            self.current_preview_video = file_path
            self.t1_video_info.configure(text=f"Loaded:\n{os.path.basename(file_path)}")
            self.log(f"Video loaded into Editor: {file_path}")

    def t1_load_src_srt(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Subtitle Files", "*.srt")])
        if file_path:
            self.src_subs = pysrt.open(file_path, encoding="utf-8")
            self.t1_refresh_lists()
            self.log(f"Loaded source subtitles: {file_path}")

    def t1_load_tgt_srt(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Subtitle Files", "*.srt")])
        if file_path:
            self.tgt_subs = pysrt.open(file_path, encoding="utf-8")
            self.t1_refresh_lists()
            self.log(f"Loaded target subtitles: {file_path}")

    def t1_refresh_lists(self):
        self.src_listbox.delete(0, tk.END)
        self.tgt_listbox.delete(0, tk.END)

        max_len = max(len(self.src_subs), len(self.tgt_subs))
        for i in range(max_len):
            src_text = self.src_subs[i].text if i < len(self.src_subs) else ""
            tgt_text = self.tgt_subs[i].text if i < len(self.tgt_subs) else ""
            self.src_listbox.insert(tk.END, f"{i+1}. {src_text}")
            self.tgt_listbox.insert(tk.END, f"{i+1}. {tgt_text}")
        self.t1_status_lbl.configure(text=f"{max_len} subtitle lines loaded.")

    def t1_on_select(self, source):
        if source == "src":
            sel = self.src_listbox.curselection()
            if sel:
                idx = sel[0]
                self.tgt_listbox.selection_clear(0, tk.END)
                self.tgt_listbox.selection_set(idx)
                self.tgt_listbox.see(idx)
        else:
            sel = self.tgt_listbox.curselection()
            if sel:
                idx = sel[0]
                self.src_listbox.selection_clear(0, tk.END)
                self.src_listbox.selection_set(idx)
                self.src_listbox.see(idx)

        idx = sel[0] if sel else None
        if idx is not None:
            s_text = self.src_subs[idx].text if idx < len(self.src_subs) else ""
            t_text = self.tgt_subs[idx].text if idx < len(self.tgt_subs) else ""
            self.t1_edit_src_entry.delete(0, tk.END)
            self.t1_edit_src_entry.insert(0, s_text)
            self.t1_edit_tgt_entry.delete(0, tk.END)
            self.t1_edit_tgt_entry.insert(0, t_text)

            if idx < len(self.src_subs):
                st = str(self.src_subs[idx].start)
                et = str(self.src_subs[idx].end)
                self.t1_time_lbl.configure(text=f"Selected Time:\n{st} --> {et}")

    def t1_commit_edit(self):
        sel = self.src_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_s = self.t1_edit_src_entry.get().strip()
        new_t = self.t1_edit_tgt_entry.get().strip()

        if idx < len(self.src_subs):
            self.src_subs[idx].text = new_s
        if idx < len(self.tgt_subs):
            self.tgt_subs[idx].text = new_t

        self.t1_refresh_lists()
        self.src_listbox.selection_set(idx)
        self.tgt_listbox.selection_set(idx)
        self.log(f"Updated line #{idx+1}")

    def t1_save_both_srts(self):
        folder = filedialog.askdirectory(title="Select Folder to Save Subtitles")
        if not folder:
            return
        src_path = os.path.join(folder, "source_edited.srt")
        tgt_path = os.path.join(folder, "target_edited.srt")
        if self.src_subs:
            self.src_subs.save(src_path, encoding="utf-8")
        if self.tgt_subs:
            self.tgt_subs.save(tgt_path, encoding="utf-8")
        self.log(f"Saved SRTs to {folder}")
        messagebox.showinfo("Saved", f"SRT files saved to:\n{folder}")

    def t1_play_full_video(self):
        if not self.current_preview_video:
            messagebox.showwarning("Warning", "Load a video first.")
            return
        self.t1_stop_player()
        cmd = [FFPLAY_BIN, "-autoexit", "-window_title", "Full Preview", self.current_preview_video]
        self.ffplay_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def t1_play_selected_segment(self):
        if not self.current_preview_video:
            messagebox.showwarning("Warning", "Load a video first.")
            return
        sel = self.src_listbox.curselection()
        if not sel or sel[0] >= len(self.src_subs):
            return
        idx = sel[0]
        item = self.src_subs[idx]
        start_secs = (item.start.hours * 3600 + item.start.minutes * 60 + item.start.seconds) + (item.start.milliseconds / 1000.0)
        dur = ((item.end.hours * 3600 + item.end.minutes * 60 + item.end.seconds) + (item.end.milliseconds / 1000.0)) - start_secs

        self.t1_stop_player()
        cmd = [
            FFPLAY_BIN, "-ss", str(start_secs), "-t", str(max(dur, 0.5)),
            "-autoexit", "-window_title", f"Segment #{idx+1}", self.current_preview_video
        ]
        self.ffplay_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def t1_stop_player(self):
        if self.ffplay_proc and self.ffplay_proc.poll() is None:
            self.ffplay_proc.terminate()
            self.ffplay_proc = None

    # =========================================================================
    # TAB 2: STANDALONE XTTS DUBBER
    # =========================================================================
    def build_tab2_xtts(self):
        frame = ttk.LabelFrame(self.tab2, text=" Dub Any Video from an SRT File ", padding=20)
        frame.pack(fill="both", expand=True, padx=25, pady=20)

        self.t2_video_var = tk.StringVar()
        self.t2_srt_var = tk.StringVar()
        self.t2_outdir_var = tk.StringVar(value="xtts_dubbed_output")
        self.t2_lang_var = tk.StringVar(value="Hindi")

        # Video Selection
        ttk.Label(frame, text="Input Video:").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t2_video_var, width=65).grid(row=0, column=1, padx=6, pady=8)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_to_var(self.t2_video_var, "video")).grid(row=0, column=2)

        # SRT Selection
        ttk.Label(frame, text="Translated SRT:").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t2_srt_var, width=65).grid(row=1, column=1, padx=6, pady=8)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_to_var(self.t2_srt_var, "srt")).grid(row=1, column=2)

        # Target Language
        ttk.Label(frame, text="Target Language:").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=self.t2_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=20).grid(row=2, column=1, sticky="w", padx=6, pady=8)

        # Output Folder
        ttk.Label(frame, text="Output Folder:").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t2_outdir_var, width=30).grid(row=3, column=1, sticky="w", padx=6, pady=8)

        # Action Button
        self.t2_btn = ttk.Button(frame, text="🎙️ Clone Voice & Generate Dubbed Video", command=self.t2_start_dubbing)
        self.t2_btn.grid(row=4, column=0, columnspan=3, pady=25, sticky="ew")

    def t2_start_dubbing(self):
        video_path = self.t2_video_var.get().strip()
        srt_path = self.t2_srt_var.get().strip()
        out_dir = self.t2_outdir_var.get().strip()
        tgt_name = self.t2_lang_var.get()
        tgt_code = LANG_MAP[tgt_name]

        if not os.path.exists(video_path) or not os.path.exists(srt_path):
            messagebox.showerror("Error", "Please select valid video and SRT files.")
            return

        self.t2_btn.configure(state="disabled")
        threading.Thread(target=self._t2_worker, args=(video_path, srt_path, out_dir, tgt_code), daemon=True).start()

    def _t2_worker(self, video_path, srt_path, out_dir, tgt_code):
        try:
            os.makedirs(out_dir, exist_ok=True)
            temp_dir = os.path.join(out_dir, "temp_segments")
            os.makedirs(temp_dir, exist_ok=True)

            orig_audio = os.path.join(out_dir, "extracted_original.wav")
            dubbed_audio = os.path.join(out_dir, "dubbed_voice.wav")
            voice_sample = os.path.join(out_dir, "voice_sample.wav")
            ext = os.path.splitext(video_path)[1]
            final_video = os.path.join(out_dir, f"dubbed_final{ext}")

            # 1. Extract audio if not present
            dub_pipeline.extract_audio(video_path, orig_audio, log_fn=self.log)

            # 2. Dub with XTTS
            subs = pysrt.open(srt_path, encoding="utf-8")
            dub_pipeline.dub_with_xtts(subs, orig_audio, dubbed_audio, voice_sample, temp_dir, tgt_code, log_fn=self.log)

            # 3. Remux
            dub_pipeline.remux_video(video_path, dubbed_audio, final_video, log_fn=self.log)

            self.log(f"\nTab 2 Dubbing complete: {final_video}")
            self.after(0, lambda: messagebox.showinfo("Success", f"Dubbing complete!\nSaved to:\n{final_video}"))
        except Exception as e:
            self.log(f"Error in Tab 2: {e}")
        finally:
            self.after(0, lambda: self.t2_btn.configure(state="normal"))

    # =========================================================================
    # TAB 3: WHISPER & QWEN TRANSCRIBE / TRANSLATE
    # =========================================================================
    def build_tab3_whisper_qwen(self):
        frame = ttk.LabelFrame(self.tab3, text=" Speech-To-Text (Whisper) & Translation (Qwen) ", padding=20)
        frame.pack(fill="both", expand=True, padx=25, pady=20)

        self.t3_video_var = tk.StringVar()
        self.t3_src_lang_var = tk.StringVar(value="Turkish")
        self.t3_tgt_lang_var = tk.StringVar(value="Hindi")
        self.t3_model_var = tk.StringVar(value="qwen3.5:9b-instruct")
        self.t3_outdir_var = tk.StringVar(value="whisper_qwen_output")

        # Video
        ttk.Label(frame, text="Input Video:").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t3_video_var, width=65).grid(row=0, column=1, padx=6, pady=8)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_to_var(self.t3_video_var, "video")).grid(row=0, column=2)

        # Languages
        ttk.Label(frame, text="Source Language:").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=self.t3_src_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=20).grid(row=1, column=1, sticky="w", padx=6, pady=8)

        ttk.Label(frame, text="Target Language:").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=self.t3_tgt_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=20).grid(row=2, column=1, sticky="w", padx=6, pady=8)

        # Model
        ttk.Label(frame, text="Ollama Model:").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t3_model_var, width=25).grid(row=3, column=1, sticky="w", padx=6, pady=8)

        # Output
        ttk.Label(frame, text="Output Folder:").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t3_outdir_var, width=25).grid(row=4, column=1, sticky="w", padx=6, pady=8)

        # Actions
        self.t3_btn = ttk.Button(frame, text="🚀 1. Transcribe & Translate -> 2. Send Directly to Editor (Tab 1)", command=self.t3_start_process)
        self.t3_btn.grid(row=5, column=0, columnspan=3, pady=25, sticky="ew")

    def t3_start_process(self):
        video_path = self.t3_video_var.get().strip()
        if not os.path.exists(video_path):
            messagebox.showerror("Error", "Please select a valid video file.")
            return

        self.t3_btn.configure(state="disabled")
        threading.Thread(target=self._t3_worker, daemon=True).start()

    def _t3_worker(self):
        try:
            video_path = self.t3_video_var.get().strip()
            out_dir = self.t3_outdir_var.get().strip()
            os.makedirs(out_dir, exist_ok=True)

            src_name = self.t3_src_lang_var.get()
            src_code = LANG_MAP[src_name]
            tgt_name = self.t3_tgt_lang_var.get()
            model_name = self.t3_model_var.get()

            audio_path = os.path.join(out_dir, "extracted_audio.wav")
            src_srt_path = os.path.join(out_dir, f"{src_name.lower()}_transcript.srt")
            tgt_srt_path = os.path.join(out_dir, f"{tgt_name.lower()}_translated.srt")

            # 1. Extract audio
            dub_pipeline.extract_audio(video_path, audio_path, log_fn=self.log)

            # 2. Whisper
            subs = dub_pipeline.transcribe_to_srt(audio_path, src_srt_path, src_name, src_code, log_fn=self.log)

            # 3. Qwen translation
            trans_subs = dub_pipeline.translate_subtitles_ollama(subs, tgt_srt_path, model_name, src_name, tgt_name, log_fn=self.log)

            # Automatically inject into Tab 1
            def _send_to_tab1():
                self.t1_load_video(video_path)
                self.src_subs = subs
                self.tgt_subs = trans_subs
                self.t1_refresh_lists()
                self.notebook.select(self.tab1)
                messagebox.showinfo("Success", "Transcription & Translation finished!\nLoaded directly into Tab 1 for review and playback.")

            self.after(0, _send_to_tab1)

        except Exception as e:
            self.log(f"Error in Tab 3: {e}")
        finally:
            self.after(0, lambda: self.t3_btn.configure(state="normal"))

    # Helper
    def browse_to_var(self, target_var, mode="video"):
        types = [("Video Files", "*.mp4 *.mov *.mkv *.avi")] if mode == "video" else [("Subtitle Files", "*.srt")]
        selected = filedialog.askopenfilename(filetypes=types)
        if selected:
            target_var.set(selected)


if __name__ == "__main__":
    app = StudioApp()
    app.mainloop()