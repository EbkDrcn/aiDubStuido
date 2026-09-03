# dub_gui.py

import os
import sys
import threading
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


class StudioApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Local Video Dubbing & Translation Studio")
        self.geometry("1120x840")
        self.minsize(950, 680)

        # Global in-memory caches
        self.src_subs = pysrt.SubRipFile()
        self.tgt_subs = pysrt.SubRipFile()
        self.current_video_path = ""
        self.current_working_dir = ""

        self.setup_ui()

    def setup_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # 1 -> Whisper & Qwen, 2 -> Editor, 3 -> XTTS
        self.tab1 = ttk.Frame(self.notebook)
        self.tab2 = ttk.Frame(self.notebook)
        self.tab3 = ttk.Frame(self.notebook)

        self.notebook.add(self.tab1, text="  1. Whisper & Qwen Studio  ")
        self.notebook.add(self.tab2, text="  2. Subtitle Editor  ")
        self.notebook.add(self.tab3, text="  3. XTTS Voice Dubbing  ")

        self.build_tab1_whisper_qwen()
        self.build_tab2_editor()
        self.build_tab3_xtts()

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
    # TAB 1: WHISPER & QWEN TRANSCRIBE / TRANSLATE
    # =========================================================================
    def build_tab1_whisper_qwen(self):
        frame = ttk.LabelFrame(self.tab1, text=" Speech-To-Text (Whisper) & Translation (Qwen) ", padding=20)
        frame.pack(fill="both", expand=True, padx=25, pady=20)

        self.t1_video_var = tk.StringVar()
        self.t1_src_lang_var = tk.StringVar(value="Turkish")
        self.t1_tgt_lang_var = tk.StringVar(value="English")
        self.t1_model_var = tk.StringVar(value="qwen2.5:7b")
        self.t1_outdir_var = tk.StringVar(value="whisper_qwen_output")

        # Input Video
        ttk.Label(frame, text="Input Video:").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t1_video_var, width=65).grid(row=0, column=1, padx=6, pady=8)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_to_var(self.t1_video_var, "video")).grid(row=0, column=2)

        # Languages
        ttk.Label(frame, text="Source Language:").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=self.t1_src_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=20).grid(row=1, column=1, sticky="w", padx=6, pady=8)

        ttk.Label(frame, text="Target Language:").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=self.t1_tgt_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=20).grid(row=2, column=1, sticky="w", padx=6, pady=8)

        # Ollama Model
        ttk.Label(frame, text="Ollama Model:").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t1_model_var, width=25).grid(row=3, column=1, sticky="w", padx=6, pady=8)

        # Output Folder
        ttk.Label(frame, text="Output Folder:").grid(row=4, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t1_outdir_var, width=25).grid(row=4, column=1, sticky="w", padx=6, pady=8)

        # Action Button
        self.t1_btn = ttk.Button(frame, text="🚀 1. Transcribe & Translate -> Send to Subtitle Editor (Tab 2)", command=self.t1_start_process)
        self.t1_btn.grid(row=5, column=0, columnspan=3, pady=25, sticky="ew")

    def t1_start_process(self):
        video_path = self.t1_video_var.get().strip().strip("{}")
        if not os.path.exists(video_path):
            messagebox.showerror("Error", "Please select a valid video file.")
            return

        self.t1_btn.configure(state="disabled")
        threading.Thread(target=self._t1_worker, daemon=True).start()

    def _t1_worker(self):
        try:
            video_path = self.t1_video_var.get().strip().strip("{}")
            out_dir = self.t1_outdir_var.get().strip()
            os.makedirs(out_dir, exist_ok=True)

            self.current_video_path = video_path
            self.current_working_dir = out_dir

            src_name = self.t1_src_lang_var.get()
            src_code = LANG_MAP[src_name]
            tgt_name = self.t1_tgt_lang_var.get()
            model_name = self.t1_model_var.get()

            audio_path = os.path.join(out_dir, "extracted_audio.wav")
            src_srt_path = os.path.join(out_dir, f"{src_name.lower()}_transcript.srt")
            tgt_srt_path = os.path.join(out_dir, f"{tgt_name.lower()}_translated.srt")

            # 1. Extract audio
            dub_pipeline.extract_audio(video_path, audio_path, log_fn=self.log)

            # 2. Whisper
            subs = dub_pipeline.transcribe_to_srt(audio_path, src_srt_path, src_name, src_code, log_fn=self.log)

            # 3. Qwen translation
            trans_subs = dub_pipeline.translate_subtitles_ollama(subs, tgt_srt_path, model_name, src_name, tgt_name, log_fn=self.log)

            def _send_to_tab2():
                self.src_subs = subs
                self.tgt_subs = trans_subs
                self.t2_refresh_table()
                # Sekme 3'teki hedef dili de otomatik ayarla
                self.t3_lang_var.set(tgt_name)
                self.notebook.select(self.tab2)
                messagebox.showinfo("Success", "Transcription & Translation finished!\nLoaded directly into Subtitle Editor (Tab 2).")

            self.after(0, _send_to_tab2)

        except Exception as e:
            self.log(f"Error in Tab 1: {e}")
        finally:
            self.after(0, lambda: self.t1_btn.configure(state="normal"))

    # =========================================================================
    # TAB 2: CRASH-FREE TREEVIEW SUBTITLE EDITOR
    # =========================================================================
    def build_tab2_editor(self):
        top_bar = ttk.Frame(self.tab2, padding=8)
        top_bar.pack(fill="x")

        ttk.Button(top_bar, text="Load Source SRT", command=self.t2_load_src_srt).pack(side="left", padx=4)
        ttk.Button(top_bar, text="Load Target SRT", command=self.t2_load_tgt_srt).pack(side="left", padx=4)
        ttk.Button(top_bar, text="Save Both SRTs", command=self.t2_save_both_srts).pack(side="left", padx=12)

        # Tab 2'den Tab 3'e Aktarım Butonu
        ttk.Button(
            top_bar, 
            text="🚀 Save & Send to XTTS Dubber (Tab 3)", 
            command=self.t2_send_to_tab3
        ).pack(side="left", padx=6)

        self.t2_status_lbl = ttk.Label(top_bar, text="No subtitles loaded.")
        self.t2_status_lbl.pack(side="right", padx=10)

        # Tablo Çerçevesi
        table_frame = ttk.Frame(self.tab2, padding=6)
        table_frame.pack(fill="both", expand=True, padx=8, pady=4)

        cols = ("idx", "start", "end", "src_text", "tgt_text")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("idx", text="#")
        self.tree.heading("start", text="Start")
        self.tree.heading("end", text="End")
        self.tree.heading("src_text", text="Source (Whisper - Original)")
        self.tree.heading("tgt_text", text="Target (Translation - Dubbing)")

        self.tree.column("idx", width=45, anchor="center")
        self.tree.column("start", width=95, anchor="center")
        self.tree.column("end", width=95, anchor="center")
        self.tree.column("src_text", width=380)
        self.tree.column("tgt_text", width=380)

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self.t2_on_tree_select)

        # Alt Düzenleme Kartı
        edit_card = ttk.LabelFrame(self.tab2, text=" Edit Selected Row ", padding=10)
        edit_card.pack(fill="x", padx=10, pady=8)

        # Satır 1: Source Line
        src_row = ttk.Frame(edit_card)
        src_row.pack(fill="x", pady=2)
        ttk.Label(src_row, text="Source Line:", width=14).pack(side="left")
        self.t2_edit_src_entry = ttk.Entry(src_row)
        self.t2_edit_src_entry.pack(side="left", fill="x", expand=True, padx=6)

        # Satır 2: Target Line
        tgt_row = ttk.Frame(edit_card)
        tgt_row.pack(fill="x", pady=2)
        ttk.Label(tgt_row, text="Target Line:", width=14).pack(side="left")
        self.t2_edit_tgt_entry = ttk.Entry(tgt_row)
        self.t2_edit_tgt_entry.pack(side="left", fill="x", expand=True, padx=6)

        self.save_row_btn = ttk.Button(edit_card, text="Update Selected Row", command=self.t2_save_row_edit)
        self.save_row_btn.pack(side="right", pady=4)

    def t2_load_src_srt(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Subtitle Files", "*.srt")])
        if file_path:
            clean_path = file_path.strip("{}").strip()
            if os.path.exists(clean_path):
                self.src_subs = pysrt.open(clean_path, encoding="utf-8")
                self.t2_refresh_table()
                self.log(f"Loaded source subtitles: {clean_path}")

    def t2_load_tgt_srt(self, file_path=None):
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Subtitle Files", "*.srt")])
        if file_path:
            clean_path = file_path.strip("{}").strip()
            if os.path.exists(clean_path):
                self.tgt_subs = pysrt.open(clean_path, encoding="utf-8")
                self.t2_refresh_table()
                self.log(f"Loaded target subtitles: {clean_path}")

    def t2_refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        max_len = max(len(self.src_subs), len(self.tgt_subs))
        for i in range(max_len):
            idx_num = i + 1
            start_str = ""
            end_str = ""
            src_txt = ""
            tgt_txt = ""

            if i < len(self.src_subs):
                src_txt = self.src_subs[i].text
                start_str = str(self.src_subs[i].start)
                end_str = str(self.src_subs[i].end)
            
            if i < len(self.tgt_subs):
                tgt_txt = self.tgt_subs[i].text
                if not start_str:
                    start_str = str(self.tgt_subs[i].start)
                    end_str = str(self.tgt_subs[i].end)

            self.tree.insert("", "end", values=(idx_num, start_str, end_str, src_txt, tgt_txt))

        self.t2_status_lbl.configure(text=f"{max_len} subtitle rows loaded.")

    def t2_on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        vals = self.tree.item(selected[0], "values")
        self.t2_edit_src_entry.delete(0, tk.END)
        self.t2_edit_src_entry.insert(0, vals[3])

        self.t2_edit_tgt_entry.delete(0, tk.END)
        self.t2_edit_tgt_entry.insert(0, vals[4])

    def t2_save_row_edit(self):
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(self.tree.item(selected[0], "values")[0])
        array_idx = idx - 1
        new_src = self.t2_edit_src_entry.get().strip()
        new_tgt = self.t2_edit_tgt_entry.get().strip()

        if array_idx < len(self.src_subs):
            self.src_subs[array_idx].text = new_src
        if array_idx < len(self.tgt_subs):
            self.tgt_subs[array_idx].text = new_tgt

        vals = list(self.tree.item(selected[0], "values"))
        vals[3] = new_src
        vals[4] = new_tgt
        self.tree.item(selected[0], values=vals)
        self.log(f"Updated row #{idx}")

    def t2_save_both_srts(self):
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

    def t2_send_to_tab3(self):
        """Altyazıları geçerli çalışma klasörüne kaydeder ve Sekme 3'e taşır."""
        if not self.tgt_subs:
            messagebox.showwarning("Warning", "No target subtitles to transfer.")
            return

        out_dir = self.current_working_dir or self.t1_outdir_var.get().strip() or "output"
        os.makedirs(out_dir, exist_ok=True)

        target_srt_path = os.path.join(out_dir, "target_edited.srt")
        source_srt_path = os.path.join(out_dir, "source_edited.srt")

        self.tgt_subs.save(target_srt_path, encoding="utf-8")
        if self.src_subs:
            self.src_subs.save(source_srt_path, encoding="utf-8")

        # Sekme 3 girdi alanlarını doldur
        if self.current_video_path:
            self.t3_video_var.set(self.current_video_path)
        elif self.t1_video_var.get():
            self.t3_video_var.set(self.t1_video_var.get())

        self.t3_srt_var.set(target_srt_path)
        self.t3_outdir_var.set(os.path.join(out_dir, "xtts_dubbed"))

        self.log(f"Approved subtitles saved to: {target_srt_path}")
        self.log("Transferred project data to XTTS Dubbing (Tab 3).")

        # Sekme 3'ü aç
        self.notebook.select(self.tab3)

    # =========================================================================
    # TAB 3: STANDALONE XTTS DUBBER
    # =========================================================================
    def build_tab3_xtts(self):
        frame = ttk.LabelFrame(self.tab3, text=" Dub Any Video from an SRT File ", padding=20)
        frame.pack(fill="both", expand=True, padx=25, pady=20)

        self.t3_video_var = tk.StringVar()
        self.t3_srt_var = tk.StringVar()
        self.t3_outdir_var = tk.StringVar(value="xtts_dubbed_output")
        self.t3_lang_var = tk.StringVar(value="English")

        # Input Video
        ttk.Label(frame, text="Input Video:").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t3_video_var, width=65).grid(row=0, column=1, padx=6, pady=8)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_to_var(self.t3_video_var, "video")).grid(row=0, column=2)

        # Translated SRT
        ttk.Label(frame, text="Translated SRT:").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t3_srt_var, width=65).grid(row=1, column=1, padx=6, pady=8)
        ttk.Button(frame, text="Browse...", command=lambda: self.browse_to_var(self.t3_srt_var, "srt")).grid(row=1, column=2)

        # Target Language
        ttk.Label(frame, text="Target Language:").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Combobox(frame, textvariable=self.t3_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=20).grid(row=2, column=1, sticky="w", padx=6, pady=8)

        # Output Folder
        ttk.Label(frame, text="Output Folder:").grid(row=3, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=self.t3_outdir_var, width=30).grid(row=3, column=1, sticky="w", padx=6, pady=8)

        # Action Button
        self.t3_btn = ttk.Button(frame, text="🎙️ Clone Voice & Generate Dubbed Video", command=self.t3_start_dubbing)
        self.t3_btn.grid(row=4, column=0, columnspan=3, pady=25, sticky="ew")

    def t3_start_dubbing(self):
        video_path = self.t3_video_var.get().strip().strip("{}")
        srt_path = self.t3_srt_var.get().strip().strip("{}")
        out_dir = self.t3_outdir_var.get().strip()
        tgt_name = self.t3_lang_var.get()
        tgt_code = LANG_MAP[tgt_name]

        if not os.path.exists(video_path) or not os.path.exists(srt_path):
            messagebox.showerror("Error", "Please select valid video and SRT files.")
            return

        self.t3_btn.configure(state="disabled")
        threading.Thread(target=self._t3_worker, args=(video_path, srt_path, out_dir, tgt_code), daemon=True).start()

    def _t3_worker(self, video_path, srt_path, out_dir, tgt_code):
        try:
            os.makedirs(out_dir, exist_ok=True)
            temp_dir = os.path.join(out_dir, "temp_segments")
            os.makedirs(temp_dir, exist_ok=True)

            orig_audio = os.path.join(out_dir, "extracted_original.wav")
            dubbed_audio = os.path.join(out_dir, "dubbed_voice.wav")
            voice_sample = os.path.join(out_dir, "voice_sample.wav")
            ext = os.path.splitext(video_path)[1]
            final_video = os.path.join(out_dir, f"dubbed_final{ext}")

            dub_pipeline.extract_audio(video_path, orig_audio, log_fn=self.log)
            subs = pysrt.open(srt_path, encoding="utf-8")
            dub_pipeline.dub_with_xtts(subs, orig_audio, dubbed_audio, voice_sample, temp_dir, tgt_code, log_fn=self.log)
            dub_pipeline.remux_video(video_path, dubbed_audio, final_video, log_fn=self.log)

            self.log(f"\nTab 3 Dubbing complete: {final_video}")
            self.after(0, lambda: messagebox.showinfo("Success", f"Dubbing complete!\nSaved to:\n{final_video}"))
        except Exception as e:
            self.log(f"Error in Tab 3: {e}")
        finally:
            self.after(0, lambda: self.t3_btn.configure(state="normal"))

    # Helper
    def browse_to_var(self, target_var, mode="video"):
        types = [("Video Files", "*.mp4 *.mov *.mkv *.avi")] if mode == "video" else [("Subtitle Files", "*.srt")]
        selected = filedialog.askopenfilename(filetypes=types)
        if selected:
            target_var.set(selected.strip("{}"))


if __name__ == "__main__":
    app = StudioApp()
    app.mainloop()